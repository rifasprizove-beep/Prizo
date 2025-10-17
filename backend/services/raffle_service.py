from __future__ import annotations
import random
import requests
import datetime as dt
from typing import List, Optional, Dict, Any, Tuple

from supabase import Client
from fastapi import HTTPException

from backend.core.settings import settings
from backend.services.utils import mask_email, cents_to_usd, round2

_HTTP_TIMEOUT = 8  # seg


class RaffleService:
    def __init__(self, client: Client):
        self.client = client
        self._settings_table = "settings"  # tabla donde cacheamos la tasa

    # ---------- Helpers de tiempo ----------
    def _now_utc(self) -> dt.datetime:
        return dt.datetime.now(dt.timezone.utc)

    def _now_iso(self) -> str:
        # PostgREST espera ISO 8601 con 'Z'
        return self._now_utc().isoformat().replace("+00:00", "Z")

    # ---------- Helpers de reservas ----------
    def _clear_expired_reservations(self, raffle_id: str) -> None:
        """
        Libera reservas expiradas (reserved_until < now) para tickets no verificados.
        Se llama antes de intentar reservar para evitar bloqueos fantasma.
        """
        now_iso = self._now_iso()
        try:
            (
                self.client.table("tickets")
                .update({"reserved_until": None, "email": None})
                .eq("raffle_id", raffle_id)
                .eq("verified", False)
                .lt("reserved_until", now_iso)
                .execute()
            )
        except Exception:
            # no interrumpir el flujo por limpieza
            pass

    # ---------- Rifas ----------
    def list_open_raffles(self) -> List[Dict[str, Any]]:
        cols = (
            "id, name, description, image_url, ticket_price_cents, currency, "
            "status, active, created_at, total_tickets, payment_methods"
        )

        q1 = (
            self.client.table("raffles")
            .select(cols)
            .eq("status", "sales_open")
            .order("created_at", desc=True)
            .execute()
        )
        data1 = q1.data or []

        q2 = (
            self.client.table("raffles")
            .select(cols)
            .eq("active", True)
            .order("created_at", desc=True)
            .execute()
        )
        data2 = q2.data or []

        seen = set()
        combined: List[Dict[str, Any]] = []
        for row in data1 + data2:
            rid = row.get("id")
            if rid and rid not in seen:
                seen.add(rid)
                combined.append(row)

        return combined

    def _extract_capacity(self, raffle_row: Dict[str, Any]) -> Optional[int]:
        if not raffle_row:
            return None
        for key in ("total_tickets", "max_tickets", "capacity"):
            if key in raffle_row and raffle_row[key] is not None:
                try:
                    val = int(raffle_row[key])
                    if val > 0:
                        return val
                except Exception:
                    continue
        return None

    def get_raffle_by_id(self, raffle_id: Optional[str]) -> Optional[Dict[str, Any]]:
        if not raffle_id:
            return self.get_current_raffle(raise_if_missing=False)
        cols = (
            "id, name, image_url, ticket_price_cents, currency, status, active, "
            "created_at, payment_methods, total_tickets"
        )
        r = (
            self.client.table("raffles")
            .select(cols)
            .eq("id", raffle_id)
            .single()
            .execute()
        )
        return r.data

    def get_current_raffle(self, raise_if_missing: bool = True) -> Optional[Dict[str, Any]]:
        rows = self.list_open_raffles()
        data = rows[0] if rows else None
        if not data and raise_if_missing:
            raise RuntimeError("No hay rifa activa (status='sales_open' o active=true).")
        return data

    # ---------- Progreso / Stocks ----------
    def _count_paid(self, raffle_id: str) -> int:
        q = (
            self.client.table("tickets")
            .select("id", count="exact")
            .eq("raffle_id", raffle_id)
            .eq("verified", True)
            .execute()
        )
        return q.count or 0

    def _count_reserved_active(self, raffle_id: str) -> int:
        """
        Reservas 'activas' = tickets sin verificar cuya reserva no ha expirado
        o que no tienen reserved_until (compatibilidad hacia atrás).
        """
        now_iso = self._now_iso()
        q = (
            self.client.table("tickets")
            .select("id", count="exact")
            .eq("raffle_id", raffle_id)
            .eq("verified", False)
            # or=(reserved_until.is.null,reserved_until.gt.<ISO>)
            .or_(f"reserved_until.is.null,reserved_until.gt.{now_iso}")
            .execute()
        )
        return q.count or 0

    def get_raffle_progress(self, raffle_id: str) -> Dict[str, Any]:
        r = (
            self.client.table("raffles")
            .select("id, total_tickets")
            .eq("id", raffle_id)
            .single()
            .execute()
        )
        raffle_row = r.data or {}
        total = self._extract_capacity(raffle_row) or 0

        sold = self._count_paid(raffle_id)
        reserved_active = self._count_reserved_active(raffle_id)

        remaining = None
        percent_sold = None
        percent_available = None
        if total:
            remaining = max(total - sold - reserved_active, 0)
            percent_sold = round2((sold / total) * 100.0)
            percent_available = round2((remaining / total) * 100.0)

        return {
            "total": total,
            "sold": sold,
            "reserved": reserved_active,
            "remaining": remaining,
            "percent_sold": percent_sold,
            "percent_available": percent_available,
        }

    def progress_for_public(self, raffle: Dict[str, Any]) -> Dict[str, Any]:
        if not raffle:
            return {}
        try:
            return self.get_raffle_progress(raffle["id"])
        except Exception:
            sold_q = (
                self.client.table("tickets")
                .select("id", count="exact")
                .eq("raffle_id", raffle["id"])
                .eq("verified", True)
                .execute()
            )
            sold = sold_q.count or 0
            return {
                "total": None,
                "sold": sold,
                "reserved": None,
                "remaining": None,
                "percent_sold": None,
                "percent_available": None,
            }

    # ---------- Tasa / BCV con caché ----------
    def _today_key(self) -> str:
        return dt.datetime.utcnow().strftime("%Y%m%d")

    def _read_cached_rate(self) -> Optional[tuple[float, str, str]]:
        r = (
            self.client.table(self._settings_table)
            .select("value")
            .eq("key", "usdves_rate")
            .limit(1)
            .execute()
        )
        if not r.data:
            return None

        val = r.data[0].get("value")
        if isinstance(val, str):
            import json
            try:
                val = json.loads(val)
            except Exception:
                return None

        if not isinstance(val, dict):
            return None

        date = str(val.get("date") or "")
        try:
            rate = float(val.get("rate") or 0)
        except Exception:
            rate = 0.0

        source = str(val.get("source") or "")
        if date == self._today_key() and rate > 0:
            return rate, source, date
        return None

    def _store_rate_cache(self, rate: float, source: str) -> None:
        payload = {"rate": float(rate), "source": source, "date": self._today_key()}
        self.client.table(self._settings_table).upsert({"key": "usdves_rate", "value": payload}).execute()

    def _num_or_none(self, x: Any) -> Optional[float]:
        try:
            n = float(str(x).replace(",", "."))
            return n if n > 0 else None
        except Exception:
            return None

    def _extract_rate_from_payload(self, j: Dict[str, Any]) -> Optional[float]:
        if not isinstance(j, dict):
            return None
        try_keys = [
            ("monitors", "bcv", "price"),
            ("monitors", "bcv", "value"),
            ("bcv", "price"),
            ("bcv", "valor"),
            ("bcv",),
            ("oficial", "price"),
            ("oficial", "valor"),
            ("usd", "bcv"),
            ("data", "usd", "bcv"),
            ("rates", "VES"),
            ("rates", "VEF"),
            ("VES",),
            ("VEF",),
            ("promedio",),
            ("price",),
            ("valor",),
        ]
        for path in try_keys:
            node = j
            ok = True
            for k in path:
                if isinstance(node, dict) and k in node:
                    node = node[k]
                else:
                    ok = False
                    break
            if ok:
                val = self._num_or_none(node)
                if val:
                    return val
        return None

    def updateBCVRate(self) -> float:
        if getattr(settings, "bcv_api_url", None):
            try:
                r = requests.get(settings.bcv_api_url, timeout=_HTTP_TIMEOUT)
                r.raise_for_status()
                j = r.json()
                rate = self._extract_rate_from_payload(j)
                if rate:
                    self._store_rate_cache(rate, f"custom:{settings.bcv_api_url}")
                    return rate
            except Exception:
                pass

        primary_sources: List[Tuple[str, str]] = [
            ("https://pydolarvenezuela.github.io/api/v1/dollar", "PyDolarVenezuela (GH Pages)"),
            ("https://pydolarvenezuela-api.vercel.app/api/v1/dollar", "PyDolarVenezuela (Vercel 1)"),
            ("https://pydolarvenezuela.vercel.app/api/v1/dollar", "PyDolarVenezuela (Vercel 2)"),
            ("https://pydolarvenezuela.obh.software/api/v1/dollar", "PyDolarVenezuela (OBH)"),
            ("https://dolartoday-api.vercel.app/api/pydolar", "dolartoday-api mirror/pydolar"),
            ("https://venezuela-exchange.vercel.app/api", "venezuela-exchange"),
        ]
        for url, label in primary_sources:
            try:
                r = requests.get(url, timeout=_HTTP_TIMEOUT)
                r.raise_for_status()
                j = r.json()
                rate = self._extract_rate_from_payload(j)
                if rate:
                    self._store_rate_cache(rate, f"BCV:{label}")
                    return rate
            except Exception:
                continue

        try:
            r = requests.get("https://open.er-api.com/v6/latest/USD", timeout=_HTTP_TIMEOUT)
            r.raise_for_status()
            j = r.json()
            rate = self._extract_rate_from_payload(j)
            if rate:
                self._store_rate_cache(rate, "MID:open.er-api.com (NO BCV)")
                return rate
        except Exception:
            pass

        try:
            r = requests.get("https://s3.amazonaws.com/dolartoday/data.json", timeout=_HTTP_TIMEOUT)
            r.raise_for_status()
            j = r.json()
            rate = self._extract_rate_from_payload(j)
            if not rate and "USD" in j and isinstance(j["USD"], dict):
                rate = self._num_or_none(j["USD"].get("promedio"))
            if rate:
                self._store_rate_cache(rate, "PAR:DolarToday S3 (NO BCV)")
                return rate
        except Exception:
            pass

        fallback = float(getattr(settings, "default_usdves_rate", 40.0))
        self._store_rate_cache(fallback, "fallback:default_usdves_rate")
        return fallback

    def get_rate(self) -> float:
        cached = self._read_cached_rate()
        if cached:
            return cached[0]
        return self.updateBCVRate()

    def get_rate_info(self) -> Dict[str, Any]:
        info = {"rate_available": False, "date": None, "source": None}
        cached = self._read_cached_rate()
        if cached:
            _, source, date = cached
            info.update({"rate_available": True, "date": date, "source": source})
        return info

    def set_rate(self, rate: float, source: str = "manual") -> Dict[str, Any]:
        payload = {"rate": float(rate), "source": source, "date": self._today_key()}
        self.client.table(self._settings_table).upsert({"key": "usdves_rate", "value": payload}).execute()
        return {"ok": True, "rate": payload["rate"], "source": source, "date": payload["date"]}

    def fetch_external_rate(self) -> float:
        if getattr(settings, "bcv_api_url", None):
            try:
                r = requests.get(settings.bcv_api_url, timeout=_HTTP_TIMEOUT)
                r.raise_for_status()
                j = r.json()
                rate = self._extract_rate_from_payload(j)
                if rate:
                    return rate
            except Exception:
                pass

        providers = (
            ("https://open.er-api.com/v6/latest/USD", "open.er-api.com"),
            ("https://dolarapi.com/v1/dolares/oficial", "dolarapi.com (BCV)"),
            ("https://api.exchangerate.host/latest?base=USD&symbols=VES", "exchangerate.host"),
        )
        for url, _name in providers:
            try:
                r = requests.get(url, timeout=_HTTP_TIMEOUT)
                r.raise_for_status()
                j = r.json()
                rate = self._extract_rate_from_payload(j)
                if rate:
                    return rate
            except Exception:
                continue

        return float(getattr(settings, "default_usdves_rate", 40.0))

    # ---------- Config pública ----------
    def public_config(self, raffle_id: Optional[str] = None) -> Dict[str, Any]:
        raffle = self.get_raffle_by_id(raffle_id)
        usd_price = cents_to_usd(raffle["ticket_price_cents"]) if raffle else None
        currency = raffle["currency"] if raffle else "USD"

        ves_per_ticket = None
        rate_meta = self.get_rate_info()
        if usd_price is not None:
            rate = self.get_rate()
            ves_per_ticket = round2(usd_price * rate)

        pm = self.get_payment_methods(raffle["id"] if raffle else None)
        progress = self.progress_for_public(raffle) if raffle else {}

        return {
            "raffle_active": bool(raffle),
            "raffle_id": raffle["id"] if raffle else None,
            "raffle_name": raffle["name"] if raffle else None,
            "image_url": raffle["image_url"] if raffle else None,
            "currency": currency,
            "usd_price": usd_price,
            "ves_price_per_ticket": ves_per_ticket,
            "ves_rate_meta": rate_meta,
            "payment_methods": pm,
            "progress": progress,
            "pagomovil_info": settings.pagomovil_info,
            "payments_bucket": settings.payments_bucket,
            "supabase_url": settings.supabase_url,
            "public_anon_key": settings.public_anon_key,
            "only_mobile_payments": True,
        }

    # ---------- Métodos de pago ----------
    def _parse_simple_kv(self, text: str) -> Dict[str, str]:
        out = {}
        if not text:
            return out
        parts = [p.strip() for p in text.replace("\r", "").split("\n") if p.strip()]
        if len(parts) == 0:
            parts = [p.strip() for p in text.split(";") if p.strip()]
        for line in parts:
            if ":" in line:
                k, v = line.split(":", 1)
            elif "=" in line:
                k, v = line.split("=", 1)
            else:
                continue
            out[k.strip()] = v.strip()
        return out

    def get_payment_methods(self, raffle_id: Optional[str]) -> Dict[str, Dict[str, str]]:
        pm: Dict[str, Dict[str, str]] = {}
        try:
            q = (
                self.client.table("raffles")
                .select("payment_methods")
                .eq("id", raffle_id)
                .single()
                .execute()
            )
            data = q.data or {}
            if isinstance(data.get("payment_methods"), dict):
                pm = data["payment_methods"] or {}
        except Exception:
            pm = {}

        if not pm:
            parsed = self._parse_simple_kv(settings.pagomovil_info)
            if parsed:
                pm = {"pago_movil": parsed}

        only_pm = {}
        if "pago_movil" in pm and isinstance(pm["pago_movil"], dict):
            only_pm["pago_movil"] = pm["pago_movil"]
        return only_pm

    # ---------- Cotización ----------
    def quote_amount(
        self,
        quantity: int,
        raffle_id: Optional[str],
        method: str,
        usd_only: bool = False,
    ) -> Dict[str, Any]:
        if quantity < 1:
            raise ValueError("quantity debe ser >= 1")

        raffle = self.get_raffle_by_id(raffle_id) or self.get_current_raffle()
        if not raffle:
            raise ValueError("No hay rifa activa ni se encontró la rifa solicitada.")

        unit_price_usd = cents_to_usd(raffle["ticket_price_cents"])
        total_usd = round2(unit_price_usd * quantity)

        rate = self.get_rate()
        unit_price_ves = round2(unit_price_usd * rate)
        total_ves = round2(total_usd * rate)

        return {
            "raffle_id": raffle["id"],
            "method": method,
            "unit_price_usd": unit_price_usd,
            "total_usd": total_usd,
            "unit_price_ves": unit_price_ves,
            "total_ves": total_ves,
        }

    # ---------- Tickets ----------
    def reserve_tickets(
        self,
        email: str,
        qty: int = 0,
        raffle_id: Optional[str] = None,
        ticket_ids: Optional[List[str]] = None,
        ticket_numbers: Optional[List[int]] = None,
    ) -> List[dict]:
        """
        Modos soportados:
        - ticket_ids: bloquea esos tickets EXISTENTES de forma atómica si están libres.
        - ticket_numbers: bloquea los números indicados; si no existen filas, las CREA y bloquea.
        - qty: comportamiento antiguo (crea N tickets nuevos y los bloquea).
        """
        raffle = self.get_raffle_by_id(raffle_id) or self.get_current_raffle()
        if not raffle or not raffle.get("active", False):
            raise ValueError("No hay rifa activa")

        raffle_id = raffle["id"]
        total_cap = self._extract_capacity(raffle) or 0
        if total_cap <= 0:
            raise ValueError("Capacidad de rifa no configurada")

        # siempre limpia reservas expiradas antes de reservar
        self._clear_expired_reservations(raffle_id)

        sold = self._count_paid(raffle_id)
        reserved_active = self._count_reserved_active(raffle_id)

        def _check_capacity(extra: int):
            if sold + reserved_active + extra > total_cap:
                raise ValueError("No hay cupos suficientes")

        expires_iso = (self._now_utc() + dt.timedelta(minutes=10)).isoformat().replace("+00:00", "Z")
        now_iso = self._now_iso()

        # ---------- 1) Reserva por IDs específicos ----------
        if ticket_ids:
            _check_capacity(len(ticket_ids))
            condition = f"reserved_until.is.null,reserved_until.lt.{now_iso}"
            upd_payload = {"email": email, "reserved_until": expires_iso}

            res = (
                self.client.table("tickets")
                .update(upd_payload)
                .in_("id", ticket_ids)
                .eq("raffle_id", raffle_id)
                .eq("verified", False)
                .or_(condition)
                .select("id")  # RETURNING
                .execute()
            )
            updated = res.data or []
            if len(updated) != len(ticket_ids):
                raise ValueError("Algunos tickets ya no están disponibles. Intenta nuevamente.")

            rows = (
                self.client.table("tickets")
                .select("*")
                .in_("id", ticket_ids)
                .execute()
                .data
                or []
            )
            return rows

        # ---------- 2) Reserva por NÚMEROS específicos ----------
        if ticket_numbers:
            unique_numbers = sorted({int(n) for n in ticket_numbers if int(n) > 0})
            if not unique_numbers:
                raise ValueError("ticket_numbers vacío")
            _check_capacity(len(unique_numbers))

            # 2.a) Intentar UPDATE en bloque para los que ya existen y estén libres
            condition = f"reserved_until.is.null,reserved_until.lt.{now_iso}"
            upd_payload = {"email": email, "reserved_until": expires_iso}
            up_res = (
                self.client.table("tickets")
                .update(upd_payload)
                .eq("raffle_id", raffle_id)
                .in_("ticket_number", unique_numbers)
                .eq("verified", False)
                .or_(condition)
                .select("id,ticket_number")
                .execute()
            )
            updated = up_res.data or []
            updated_nums = {row["ticket_number"] for row in updated}

            # 2.b) Para los números que NO existían o no estaban libres, intentar CREAR filas
            to_create = [n for n in unique_numbers if n not in updated_nums]
            created_rows: List[dict] = []
            for num in to_create:
                row = {
                    "raffle_id": raffle_id,
                    "email": email,
                    "ticket_number": int(num),
                    "verified": False,
                    "reference": None,
                    "evidence_url": None,
                    "reserved_until": expires_iso,
                }
                try:
                    ins = self.client.table("tickets").insert(row).select("*").execute()
                    if ins.data:
                        created_rows.append(ins.data[0])
                        continue
                except Exception:
                    # si hubo conflicto (ya lo crearon), reintenta UPDATE de liberación
                    pass

                # Reintento final: si existe y está libre, lo tomo; si no, fallo
                retry = (
                    self.client.table("tickets")
                    .update({"email": email, "reserved_until": expires_iso})
                    .eq("raffle_id", raffle_id)
                    .eq("ticket_number", int(num))
                    .eq("verified", False)
                    .or_(condition)
                    .select("*")
                    .execute()
                ).data or []
                if retry:
                    created_rows.append(retry[0])
                else:
                    raise ValueError(f"El ticket #{num} ya no está disponible")

            # Combinar actualizados + creados y devolver completos
            all_ids = [r["id"] for r in created_rows] + [r["id"] for r in updated]
            rows = (
                self.client.table("tickets")
                .select("*")
                .in_("id", all_ids)
                .execute()
            ).data or []
            return rows

        # ---------- 3) Comportamiento anterior (crear N nuevos) ----------
        if qty < 1:
            raise ValueError("quantity must be >= 1")

        _check_capacity(qty)

        created_rows: List[dict] = []
        for _ in range(qty):
            last = (
                self.client.table("tickets")
                .select("ticket_number", count=None)
                .eq("raffle_id", raffle_id)
                .order("ticket_number", desc=True)
                .limit(1)
                .execute()
            )
            last_num = last.data[0]["ticket_number"] if (last.data or []) else 0
            next_num = int(last_num) + 1

            row = {
                "raffle_id": raffle_id,
                "email": email,
                "ticket_number": next_num,
                "verified": False,
                "reference": None,
                "evidence_url": None,
                "reserved_until": expires_iso,  # bloqueo temporal
            }
            ins = self.client.table("tickets").insert(row).select("*").execute()
            created_rows.append(ins.data[0])

        return created_rows

    def mark_paid(self, ticket_ids: List[str], payment_ref: str):
        if not ticket_ids:
            return
        self.client.table("tickets").update(
            {"verified": True, "reference": payment_ref, "reserved_until": None}
        ).in_("id", ticket_ids).execute()

    # ---------- Pagos ----------
    def create_mobile_payment(
        self,
        email: str,
        quantity: int,
        reference: str,
        evidence_url: Optional[str],
        raffle_id: Optional[str] = None,
        method: Optional[str] = None,
    ) -> Dict[str, Any]:
        if quantity < 1:
            raise ValueError("quantity debe ser >= 1")
        raffle = self.get_raffle_by_id(raffle_id) or self.get_current_raffle()
        if not raffle:
            raise ValueError("No hay rifa activa para registrar pagos.")

        pay = {
            "raffle_id": raffle["id"],
            "email": email,
            "quantity": quantity,
            "reference": reference,
            "evidence_url": evidence_url,
            "status": "pending",
            "method": (method or "pago_movil"),
        }
        presp = self.client.table("payments").insert(pay).select("id").execute()
        if not presp.data:
            raise RuntimeError("No se pudo registrar el pago en la tabla de pagos.")
        payment_id = presp.data[0]["id"]

        # Reserva inmediata de N tickets nuevos (flujo actual).
        tickets_creados = self.reserve_tickets(email, quantity, raffle_id=raffle["id"])
        ticket_ids = [t["id"] for t in tickets_creados]

        links = [{"payment_id": payment_id, "ticket_id": tid} for tid in ticket_ids]
        self.client.table("payment_tickets").insert(links).execute()

        return {"payment_id": payment_id, "status": "pending", "raffle_id": raffle["id"]}

    def admin_verify_payment(self, payment_id: str, approve: bool) -> Dict[str, Any]:
        links = (
            self.client.table("payment_tickets")
            .select("ticket_id")
            .eq("payment_id", payment_id)
            .execute()
        )
        ticket_ids = [x["ticket_id"] for x in (links.data or [])]
        if not ticket_ids:
            raise HTTPException(404, "Pago no encontrado o sin tickets asociados")

        new_payment_status = "approved" if approve else "rejected"

        paydata = (
            self.client.table("payments")
            .select("reference")
            .eq("id", payment_id)
            .limit(1)
            .execute()
            .data
        )
        ref = (paydata[0]["reference"] if paydata else f"PAY-{payment_id}")

        if approve:
            self.mark_paid(ticket_ids, ref)

        self.client.table("payments").update({"status": new_payment_status}).eq("id", payment_id).execute()

        return {"payment_id": payment_id, "status": new_payment_status, "ticket_ids": ticket_ids}

    # ---------- Consultas ----------
    def check_status(self, ticket_number: Optional[int], reference: Optional[str], email: Optional[str]) -> List[Dict[str, Any]]:
        if not any([ticket_number, reference, email]):
            raise HTTPException(status_code=400, detail="Se requiere al menos un criterio de búsqueda.")

        payment_ids = set()

        if reference or email:
            query = self.client.table("payments").select("id")
            if reference:
                query = query.eq("reference", reference)
            if email:
                query = query.eq("email", email)
            res = query.execute()
            for p in (res.data or []):
                payment_ids.add(p["id"])

        if ticket_number:
            t_res = self.client.table("tickets").select("id").eq("ticket_number", ticket_number).execute()
            if t_res.data:
                link_res = (
                    self.client.table("payment_tickets")
                    .select("payment_id")
                    .eq("ticket_id", t_res.data[0]["id"])
                    .execute()
                )
                for link in (link_res.data or []):
                    payment_ids.add(link["payment_id"])

        if not payment_ids:
            return []

        payments = (
            self.client.table("payments")
            .select("*")
            .in_("id", list(payment_ids))
            .execute()
            .data
        ) or []

        final_result = []
        for payment in payments:
            tickets_res = (
                self.client.table("payment_tickets")
                .select("tickets(ticket_number)")
                .eq("payment_id", payment["id"])
                .execute()
            )
            numbers = [
                t["tickets"]["ticket_number"]
                for t in (tickets_res.data or [])
                if t.get("tickets") and t["tickets"].get("ticket_number")
            ]
            final_result.append(
                {
                    "email_masked": mask_email(payment["email"]),
                    "reference": payment["reference"],
                    "ticket_numbers": sorted(numbers),
                    "status": payment["status"],
                    "purchase_date": payment["created_at"],
                }
            )
        return final_result

    # ---------- Sorteo ----------
    def start_draw(self, seed: Optional[int]) -> str:
        raffle = self.get_current_raffle()
        resp = self.client.table("draws").insert({"raffle_id": raffle["id"], "seed": seed}).execute()
        if not resp.data:
            raise RuntimeError("No se pudo iniciar el sorteo")
        return resp.data[0]["id"]

    def get_latest_draw_for_current_raffle(self) -> Optional[Dict[str, Any]]:
        raffle = self.get_current_raffle()
        r = (
            self.client.table("draws")
            .select("id, raffle_id, started_at")
            .eq("raffle_id", raffle["id"])
            .order("started_at", desc=True)
            .limit(1)
            .execute()
        )
        return r.data[0] if r.data else None

    def pick_winners(self, draw_id: str, n: int, unique: bool = True) -> List[Dict[str, Any]]:
        raffle = self.get_current_raffle()
        paid = (
            self.client.table("tickets")
            .select("id, ticket_number, email")
            .eq("raffle_id", raffle["id"])
            .eq("verified", True)
            .order("ticket_number")
            .execute()
        )
        records = paid.data or []
        if not records:
            return []

        rng = random.Random()
        pool = list(records)

        if unique:
            chosen = rng.sample(pool, n) if n <= len(pool) else pool
        else:
            chosen = [rng.choice(pool) for _ in range(n)]

        rows = [
            {
                "draw_id": draw_id,
                "raffle_id": raffle["id"],
                "ticket_id": c["id"],
                "position": i + 1,
                "ticket_number": c["ticket_number"],
            }
            for i, c in enumerate(chosen)
        ]
        if not rows:
            return []

        inserted = self.client.table("winners").insert(rows).select("id, position, ticket_id").execute().data
        by_tid = {c["id"]: c for c in chosen}

        return [
            {
                "winner_id": w["id"],
                "position": w["position"],
                "ticket_id": w["ticket_id"],
                "ticket_number": by_tid[w["ticket_id"]]["ticket_number"],
                "email_masked": mask_email(by_tid[w["ticket_id"]]["email"]),
            }
            for w in (inserted or [])
        ]
