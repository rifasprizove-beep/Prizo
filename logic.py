from __future__ import annotations
import random
import requests
import datetime as dt
from typing import List, Optional, Dict, Any, Tuple
from os import getenv
from decimal import Decimal, ROUND_HALF_UP

from pydantic import BaseModel
from supabase import create_client, Client
from fastapi import HTTPException  # para errores de API


# =========================
#        SETTINGS
# =========================
class Settings(BaseModel):
    supabase_url: str = getenv("SUPABASE_URL", "")
    supabase_service_key: str = getenv("SUPABASE_SERVICE_KEY", "")
    public_anon_key: str = getenv("PUBLIC_SUPABASE_ANON_KEY", "")

    # Tasa por defecto si todo falla (respaldo)
    default_usdves_rate: float = float(getenv("USDVES_RATE", "38.0"))

    # Texto por defecto de métodos locales (si backend no trae campos estructurados)
    pagomovil_info: str = getenv("PAYMENT_METHODS_INFO", "Pago Móvil no configurado")

    payments_bucket: str = getenv("PAYMENTS_BUCKET", "payments")
    admin_api_key: str = getenv("ADMIN_API_KEY", "")

    # Si quieres forzar una API, setéala; si no, se usan fallbacks
    bcv_api_url: str = getenv("BCV_API_URL", "")

settings = Settings()


def make_client() -> Client:
    if not settings.supabase_url or not settings.supabase_service_key:
        raise RuntimeError("Faltan SUPABASE_URL o SUPABASE_SERVICE_KEY")
    return create_client(settings.supabase_url, settings.supabase_service_key)


# =========================
#     HELPERS GENERALES
# =========================
def _mask_email(email: str) -> str:
    if not email or "@" not in email:
        return email
    user, dom = email.split("@", 1)

    def mask(s: str) -> str:
        if len(s) <= 2:
            return s[:1] + "*"
        return s[:2] + "***"

    dom_parts = dom.split(".")
    dom_parts[0] = mask(dom_parts[0])
    return f"{mask(user)}@{'.'.join(dom_parts)}"


def cents_to_usd(cents: int) -> float:
    return round(cents / 100.0, 2)


def _round2(x: float | Decimal) -> float:
    if not isinstance(x, Decimal):
        x = Decimal(str(x))
    return float(x.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# =========================
#        SERVICIO
# =========================
_HTTP_TIMEOUT = 8  # seg

class RaffleService:
    def __init__(self, client: Client):
        self.client = client
        self._settings_table = "settings"  # tabla donde cacheamos la tasa

    # ---------- Rifas ----------
    def list_open_raffles(self) -> List[Dict[str, Any]]:
        cols = (
            "id, name, description, image_url, ticket_price_cents, currency, "
            "status, active, created_at, total_tickets, payment_methods"
            )

        # 1) rifas con status = sales_open
        q1 = (
        self.client.table("raffles")
            .select(cols)
            .eq("status", "sales_open")
            .order("created_at", desc=True)
            .execute()
        )
        data1 = q1.data or []

        # 2) rifas con active = true (por si el status no quedó seteado)
        q2 = (
            self.client.table("raffles")
            .select(cols)
            .eq("active", True)
            .order("created_at", desc=True)
            .execute()
        )
        data2 = q2.data or []

    # 3) combinar por id para evitar duplicados
        seen = set()
        combined: List[Dict[str, Any]] = []
        for row in data1 + data2:
            rid = row.get("id")
            if rid and rid not in seen:
                seen.add(rid)
                combined.append(row)

        return combined


    def _extract_capacity(self, raffle_row: Dict[str, Any]) -> Optional[int]:
        """
        Devuelve la capacidad total de tickets de la rifa.
        Orden de preferencia: total_tickets > max_tickets > capacity.
        (Si las últimas no existen, ignora y usa total_tickets).
        """
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
    def get_raffle_progress(self, raffle_id: str) -> Dict[str, Any]:
        """
        Calcula progreso: total, vendidos(verified), reservados(no verificados),
        restantes y porcentajes.
        """
        # capacidad (solo pedimos columnas reales)
        r = (
            self.client.table("raffles")
            .select("id, total_tickets")
            .eq("id", raffle_id)
            .single()
            .execute()
        )
        raffle_row = r.data or {}
        total = self._extract_capacity(raffle_row) or 0

        # vendidos = verified true
        sold_q = (
            self.client.table("tickets")
            .select("id", count="exact")
            .eq("raffle_id", raffle_id)
            .eq("verified", True)
            .execute()
        )
        sold = sold_q.count or 0

        # reservados = no verificados (creados pero pendientes)
        res_q = (
            self.client.table("tickets")
            .select("id", count="exact")
            .eq("raffle_id", raffle_id)
            .eq("verified", False)
            .execute()
        )
        reserved = res_q.count or 0

        remaining = max(total - sold, 0) if total else None
        percent_sold = _round2((sold / total) * 100.0) if total else None
        percent_available = _round2((remaining / total) * 100.0) if (total and remaining is not None) else None

        return {
            "total": total,
            "sold": sold,
            "reserved": reserved,
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
            # fallback sin capacidad: al menos devolvemos conteos básicos
            sold_q = (
                self.client.table("tickets")
                .select("id", count="exact")
                .eq("raffle_id", raffle["id"])
                .eq("verified", True)
                .execute()
            )
            sold = sold_q.count or 0
            return {"total": None, "sold": sold, "reserved": None, "remaining": None, "percent_sold": None, "percent_available": None}

    # ---------- Tasa / BCV con caché ----------
    def _today_key(self) -> str:
        return dt.datetime.utcnow().strftime("%Y%m%d")

    def _read_cached_rate(self) -> Optional[Tuple[float, str, str]]:
        """
        Lee la tasa cacheada en settings (key='usdves_rate').
        Retorna (rate, source, date) o None si no hay válida para hoy.
        """
        r = (
            self.client.table(self._settings_table)
            .select("value")
            .eq("key", "usdves_rate")
            .limit(1)
            .execute()
        )
        if not r.data:
            return None
        val = r.data[0]["value"] or {}
        date = str(val.get("date") or "")
        rate = float(val.get("rate") or 0)
        source = val.get("source") or ""
        if date == self._today_key() and rate > 0:
            return rate, source, date
        return None

    def get_rate(self) -> float:
        """
        Devuelve tasa USD→VES del día. Usa caché en BD;
        si está caducada o no existe, actualiza desde proveedores.
        """
        cached = self._read_cached_rate()
        if cached:
            return cached[0]

        rate = self.fetch_external_rate()
        self.set_rate(rate, source="auto_api")
        return rate

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
        """
        Intenta leer raffles.payment_methods (si existe).
        Si no existe o viene vacío, devuelve un fallback armado con PAYMENT_METHODS_INFO.
        SOLO devolvemos 'pago_movil' porque así lo pediste.
        """
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

        # Fallback: convertir PAYMENT_METHODS_INFO en bloque para pago_movil
        if not pm:
            parsed = self._parse_simple_kv(settings.pagomovil_info)
            if parsed:
                pm = {"pago_movil": parsed}

        # Filtramos a solo pago_movil
        only_pm = {}
        if "pago_movil" in pm and isinstance(pm["pago_movil"], dict):
            only_pm["pago_movil"] = pm["pago_movil"]
        return only_pm

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
        """
        Intenta obtener la tasa desde varios proveedores (en orden).
        Acepta tanto 'VES' como el legacy 'VEF' si aparece.
        Si todo falla, retorna la tasa por defecto de env.
        """
        # 1) Forzada por env (si existe)
        if settings.bcv_api_url:
            try:
                r = requests.get(settings.bcv_api_url, timeout=_HTTP_TIMEOUT)
                r.raise_for_status()
                j = r.json()
                if "rates" in j and ("VES" in j["rates"] or "VEF" in j["rates"]):
                    return float(j["rates"].get("VES") or j["rates"].get("VEF"))
                if "VES" in j:
                    return float(j["VES"])
            except Exception:
                pass  # sigue a fallbacks

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

                # open.er-api.com y exchangerate.host
                if "rates" in j:
                    if "VES" in j["rates"]:
                        return float(j["rates"]["VES"])
                    if "VEF" in j["rates"]:
                        return float(j["rates"]["VEF"])  # legacy

                # dolarapi (campo 'promedio')
                if "promedio" in j:
                    return float(j["promedio"])

                # fallback genérico: {"VES": xx}
                if "VES" in j:
                    return float(j["VES"])

            except Exception:
                continue

        # último recurso
        return settings.default_usdves_rate

    # ---------- Config pública ----------
    def public_config(self, raffle_id: Optional[str] = None) -> Dict[str, Any]:
        raffle = self.get_raffle_by_id(raffle_id)
        usd_price = cents_to_usd(raffle["ticket_price_cents"]) if raffle else None
        currency = raffle["currency"] if raffle else "USD"

        ves_per_ticket = None
        rate_meta = self.get_rate_info()
        if usd_price is not None:
            rate = self.get_rate()
            ves_per_ticket = _round2(usd_price * rate)

        # Métodos de pago (solo pago_movil)
        pm = self.get_payment_methods(raffle["id"] if raffle else None)

        # Progreso
        progress = self.progress_for_public(raffle) if raffle else {}

        return {
            "raffle_active": bool(raffle),
            "raffle_id": raffle["id"] if raffle else None,
            "raffle_name": raffle["name"] if raffle else None,
            "image_url": raffle["image_url"] if raffle else None,
            "currency": currency,
            "usd_price": usd_price,
            "ves_price_per_ticket": ves_per_ticket,   # <- mostrar solo Bs en el front
            "ves_rate_meta": rate_meta,               # <- metadatos de tasa (sin mostrar valor si no quieres)
            "payment_methods": pm,                    # <- SOLO pago móvil
            "progress": progress,                     # <- para la barra de avance
            "pagomovil_info": settings.pagomovil_info,
            "payments_bucket": settings.payments_bucket,
            "supabase_url": settings.supabase_url,
            "public_anon_key": settings.public_anon_key,
            "only_mobile_payments": True,
        }

    # ---------- Cotización ----------
    def quote_amount(
        self,
        quantity: int,
        raffle_id: Optional[str],
        method: str,
        usd_only: bool = False,
    ) -> Dict[str, Any]:
        """
        Calcula totales según cantidad, rifa y método.
        - usd_only NO se usa para mostrar; dejamos todo en VES para front.
        """
        if quantity < 1:
            raise ValueError("quantity debe ser >= 1")

        raffle = self.get_raffle_by_id(raffle_id) or self.get_current_raffle()
        if not raffle:
            raise ValueError("No hay rifa activa ni se encontró la rifa solicitada.")

        unit_price_usd = cents_to_usd(raffle["ticket_price_cents"])
        total_usd = _round2(unit_price_usd * quantity)

        rate = self.get_rate()
        unit_price_ves = _round2(unit_price_usd * rate)
        total_ves = _round2(total_usd * rate)

        return {
            "raffle_id": raffle["id"],
            "method": method,
            "unit_price_usd": unit_price_usd,
            "total_usd": total_usd,
            "unit_price_ves": unit_price_ves,
            "total_ves": total_ves,
        }

    # ---------- Tickets ----------
    def reserve_tickets(self, email: str, quantity: int, raffle_id: Optional[str] = None) -> List[Dict[str, Any]]:
        if quantity < 1:
            raise ValueError("quantity debe ser >= 1")
        raffle = self.get_raffle_by_id(raffle_id) or self.get_current_raffle()
        if not raffle:
            raise ValueError("No hay rifa activa para reservar tickets.")
        rows = [{"raffle_id": raffle["id"], "email": email, "verified": False} for _ in range(quantity)]
        resp = self.client.table("tickets").insert(rows).select("id, ticket_number").execute()
        if not resp.data:
            raise RuntimeError("No se pudieron crear los tickets")
        return resp.data

    def mark_paid(self, ticket_ids: List[str], payment_ref: str):
        if not ticket_ids:
            return
        self.client.table("tickets").update({"verified": True, "reference": payment_ref}).in_("id", ticket_ids).execute()

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
                    "email_masked": _mask_email(payment["email"]),
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
                "email_masked": _mask_email(by_tid[w["ticket_id"]]["email"]),
            }
            for w in (inserted or [])
        ]
