from __future__ import annotations
import random, requests, datetime as dt
from typing import List, Optional, Dict, Any
from os import getenv
from pydantic import BaseModel
from supabase import create_client, Client
from fastapi import HTTPException  # Importo HTTPException para usarlo en varias funciones

# ---------- Settings (sin exponer tasa en el front) ----------
class Settings(BaseModel):
    supabase_url: str = getenv("SUPABASE_URL", "")
    supabase_service_key: str = getenv("SUPABASE_SERVICE_KEY", "")
    public_anon_key: str = getenv("PUBLIC_SUPABASE_ANON_KEY", "")
    default_usdves_rate: float = float(getenv("USDVES_RATE", "38.0"))
    pagomovil_info: str = getenv("PAYMENT_METHODS_INFO", "Pago Móvil no configurado")  # Nombre más genérico
    payments_bucket: str = getenv("PAYMENTS_BUCKET", "payments")
    admin_api_key: str = getenv("ADMIN_API_KEY", "")
    bcv_api_url: str = getenv("BCV_API_URL", "")

settings = Settings()

def make_client() -> Client:
    if not settings.supabase_url or not settings.supabase_service_key:
        raise RuntimeError("Faltan SUPABASE_URL o SUPABASE_SERVICE_KEY")
    return create_client(settings.supabase_url, settings.supabase_service_key)

def _mask_email(email: str) -> str:
    if not email or "@" not in email:
        return email
    user, dom = email.split("@", 1)
    def mask(s: str) -> str:
        if len(s) <= 2: return s[:1] + "*"
        return s[:2] + "***"
    dom_parts = dom.split(".")
    dom_parts[0] = mask(dom_parts[0])
    return f"{mask(user)}@{'.'.join(dom_parts)}"

def cents_to_usd(cents: int) -> float:
    return round(cents / 100.0, 2)

# ---------- Servicio ----------
class RaffleService:
    def __init__(self, client: Client):
        self.client = client

    # ===== Rifas disponibles (NUEVO) =====
    def list_open_raffles(self) -> List[Dict[str, Any]]:
        r = (
            self.client.table("raffles")
            .select("id, name, description, ticket_price_cents, currency, status, created_at")
            .eq("status", "sales_open")
            .order("created_at", desc=True)
            .execute()
        )
        return r.data or []

    # ===== Rifa por ID (NUEVO) =====
    def get_raffle_by_id(self, raffle_id: Optional[str]) -> Optional[Dict[str, Any]]:
        if not raffle_id:
            return self.get_current_raffle(raise_if_missing=False)
        r = (
            self.client.table("raffles")
            .select("id, name, ticket_price_cents, currency, status, created_at")
            .eq("id", raffle_id)
            .single()
            .execute()
        )
        return r.data

    # ===== Rifa activa (SIN CAMBIOS) =====
    def get_current_raffle(self, raise_if_missing: bool = True) -> Optional[Dict[str, Any]]:
        r = (
            self.client.table("raffles")
            .select("id, name, ticket_price_cents, currency, status, created_at")
            .eq("status", "sales_open")
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        data = r.data[0] if r.data else None
        if not data and raise_if_missing:
            raise RuntimeError("No hay rifa activa (status='sales_open').")
        return data

    # ===== Tasa BCV (AHORA CON LA API QUE PEDISTE) =====
    def _today_key(self) -> str:
        return dt.datetime.utcnow().strftime("%Y%m%d")

    def get_rate(self) -> float:
        """
        Devuelve tasa USD→VES del día. Intenta obtenerla de la BD (cache).
        Si no está o es vieja, llama a fetch_external_rate para actualizarla.
        """
        today = self._today_key()
        r = self.client.table("app_settings").select("value").eq("key", "usdves_rate").limit(1).execute()
        if r.data:
            val = r.data[0]["value"]
            if val and str(val.get("date")) == today and float(val.get("rate", 0)) > 0:
                # Tasa válida desde caché
                return float(val["rate"])

        # Caché inválido → obtener y guardar
        rate = self.fetch_external_rate()
        self.set_rate(rate, source="auto_api")
        return rate

    def set_rate(self, rate: float, source: str = "manual") -> Dict[str, Any]:
        """Guarda la tasa obtenida en la base de datos para usarla como caché."""
        payload = {"rate": float(rate), "source": source, "date": self._today_key()}
        self.client.table("app_settings").upsert({"key": "usdves_rate", "value": payload}).execute()
        return {"ok": True, "rate": payload["rate"], "source": source, "date": payload["date"]}

    def fetch_external_rate(self) -> float:
        """
        Intenta obtener la tasa de cambio desde la API open.er-api.com.
        Si falla, usa el valor por defecto de las variables de entorno.
        """
        api_url = "https://open.er-api.com/v6/latest/USD"
        try:
            res = requests.get(api_url, timeout=10)  # Timeout de 10 segundos
            res.raise_for_status()  # Lanza un error si la respuesta no es 200 OK
            data = res.json()
            if data.get("result") == "success" and "rates" in data and "VES" in data["rates"]:
                return float(data["rates"]["VES"])
        except requests.exceptions.RequestException:
            pass
        return settings.default_usdves_rate

    # ===== Config pública (ACTUALIZADA: acepta raffle_id opcional) =====
    def public_config(self, raffle_id: Optional[str] = None) -> Dict[str, Any]:
        """
        Si raffle_id viene, devuelve la config de esa rifa; de lo contrario usa la rifa activa.
        """
        raffle = self.get_raffle_by_id(raffle_id)
        usd_price = cents_to_usd(raffle["ticket_price_cents"]) if raffle else None
        currency = raffle["currency"] if raffle else "USD"
        ves_per_ticket = None
        if usd_price is not None:
            rate = self.get_rate()
            ves_per_ticket = round(usd_price * rate, 2)
        return {
            "raffle_active": bool(raffle),
            "raffle_id": raffle["id"] if raffle else None,
            "raffle_name": raffle["name"] if raffle else None,
            "currency": currency,
            "usd_price": usd_price,
            "ves_price_per_ticket": ves_per_ticket,
            "pagomovil_info": settings.pagomovil_info,
            "payments_bucket": settings.payments_bucket,
            "supabase_url": settings.supabase_url,
            "public_anon_key": settings.public_anon_key,
        }

    # ===== Tickets (ACTUALIZADA: acepta raffle_id opcional) =====
    def reserve_tickets(self, email: str, quantity: int, raffle_id: Optional[str] = None) -> List[Dict[str, Any]]:
        if quantity < 1:
            raise ValueError("quantity debe ser >= 1")
        raffle = self.get_raffle_by_id(raffle_id) or self.get_current_raffle()
        # Tu tabla `tickets` tiene `verified` (bool), no `status`
        rows = [{"raffle_id": raffle["id"], "email": email, "verified": False} for _ in range(quantity)]
        # Tu tabla `tickets` tiene `ticket_number` que es autoincremental
        resp = self.client.table("tickets").insert(rows).select("id, ticket_number").execute()
        if not resp.data:
            raise RuntimeError("No se pudieron crear los tickets")
        return resp.data

    def mark_paid(self, ticket_ids: List[str], payment_ref: str):
        if not ticket_ids:
            return
        # Tu tabla `tickets` tiene `reference` y `verified`
        self.client.table("tickets").update({"verified": True, "reference": payment_ref}).in_("id", ticket_ids).execute()

    # ===== Pago Móvil (ACTUALIZADA: añade raffle_id opcional, robusta) =====
    def create_mobile_payment(
        self,
        email: str,
        quantity: int,
        reference: str,
        evidence_url: Optional[str],
        raffle_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        if quantity < 1:
            raise ValueError("quantity debe ser >= 1")
        raffle = self.get_raffle_by_id(raffle_id) or self.get_current_raffle()

        # Creación del registro de pago en la tabla `payments`
        pay = {
            "raffle_id": raffle["id"],
            "email": email,
            "quantity": quantity,
            "reference": reference,
            "evidence_url": evidence_url,
            "status": "pending",  # Usando la columna `status`
        }
        presp = self.client.table("payments").insert(pay).select("id").execute()
        if not presp.data:
            raise RuntimeError("No se pudo registrar el pago en la tabla de pagos.")
        payment_id = presp.data[0]["id"]

        # Reservar los tickets. ¡Esto es importante para que el admin los vea!
        tickets_creados = self.reserve_tickets(email, quantity, raffle_id=raffle["id"])
        ticket_ids = [t["id"] for t in tickets_creados]

        # Vincular el pago con los tickets (requiere tabla puente `payment_tickets`)
        links = [{"payment_id": payment_id, "ticket_id": tid} for tid in ticket_ids]
        self.client.table("payment_tickets").insert(links).execute()

        return {"payment_id": payment_id, "status": "pending", "raffle_id": raffle["id"]}

    # ===== Admin (MISMO FLUJO; usa `status`) =====
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

        # 1. Obtener la referencia del pago
        paydata = (
            self.client.table("payments")
            .select("reference")
            .eq("id", payment_id)
            .single()
            .execute()
            .data
        )
        ref = paydata["reference"] if paydata else f"PAY-{payment_id}"

        # 2. Marcar los tickets como pagados y verificados (si apruebo)
        if approve:
            self.mark_paid(ticket_ids, ref)

        # 3. Actualizar el estado del pago principal
        self.client.table("payments").update({"status": new_payment_status}).eq("id", payment_id).execute()

        return {"payment_id": payment_id, "status": new_payment_status, "ticket_ids": ticket_ids}

    # ===== Verificar Ticket / Pago (SIN CAMBIOS) =====
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
            for p in res.data:
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
                for link in link_res.data:
                    payment_ids.add(link["payment_id"])

        if not payment_ids:
            return []

        payments = (
            self.client.table("payments")
            .select("*")
            .in_("id", list(payment_ids))
            .execute()
            .data
        )
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
                for t in tickets_res.data
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

    # ===== Sorteo (SIN CAMBIOS) =====
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
            .select("id, ticket_number, email")  # Usamos 'ticket_number'
            .eq("raffle_id", raffle["id"])
            .eq("verified", True)  # Pagados/verificados
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
            for w in inserted
        ]
