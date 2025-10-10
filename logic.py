# logic.py
from __future__ import annotations
import random, requests, datetime as dt
from typing import List, Optional, Dict, Any
from os import getenv
from pydantic import BaseModel
from supabase import create_client, Client

# ---------- Settings (sin exponer tasa en el front) ----------
class Settings(BaseModel):
    supabase_url: str = getenv("SUPABASE_URL", "")
    supabase_service_key: str = getenv("SUPABASE_SERVICE_KEY", "")
    public_anon_key: str = getenv("PUBLIC_SUPABASE_ANON_KEY", "")
    default_usdves_rate: float = float(getenv("USDVES_RATE", "38.0"))  # respaldo
    pagomovil_info: str = getenv("PAGOMOVIL_INFO", "Pago Móvil no configurado")
    payments_bucket: str = getenv("PAYMENTS_BUCKET", "payments")
    admin_api_key: str = getenv("ADMIN_API_KEY", "")
    # opcional: proveedor propio
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
    """
    Tablas:
      raffles(id, name, status, ticket_price_cents, currency, created_at)
      tickets(id, raffle_id, email, number, status, payment_ref, created_at)
      payments(id, raffle_id, email, quantity, usd_amount, ves_rate, ves_amount, reference, evidence_url, status)
      payment_tickets(payment_id, ticket_id)
      draws(id, raffle_id, seed, started_at)
      winners(id, draw_id, raffle_id, ticket_id, position)
      app_settings(key, value, updated_at)  -- guarda {rate, source, yyyymmdd}
    """
    def __init__(self, client: Client):
        self.client = client

    # ===== Rifa activa =====
    def get_current_raffle(self, raise_if_missing: bool = True) -> Optional[Dict[str, Any]]:
        r = (self.client.table("raffles")
             .select("id, name, ticket_price_cents, currency, status, created_at")
             .eq("status", "sales_open")
             .order("created_at", desc=True)
             .limit(1)
             .execute())
        data = r.data[0] if r.data else None
        if not data and raise_if_missing:
            raise RuntimeError("No hay rifa activa (status='sales_open').")
        return data

    # ===== Tasa BCV (oculta) =====
    def _today_key(self) -> str:
        return dt.datetime.utcnow().strftime("%Y%m%d")

    def get_rate(self) -> float:
        """Devuelve tasa USD→VES del día (cacheada en app_settings)."""
        today = self._today_key()
        r = self.client.table("app_settings").select("value").eq("key", "usdves_rate").limit(1).execute()
        if r.data:
            val = r.data[0]["value"]
            if val and str(val.get("date")) == today and float(val.get("rate", 0)) > 0:
                return float(val["rate"])
        # si no hay o está viejo, refrescamos
        rate = self.fetch_external_rate()
        self.set_rate(rate, source=val.get("source", "auto") if r.data else "auto")
        return rate

    def set_rate(self, rate: float, source: str = "manual") -> Dict[str, Any]:
        payload = {"rate": float(rate), "source": source, "date": self._today_key()}
        self.client.table("app_settings").upsert({"key": "usdves_rate", "value": payload}).execute()
        return {"ok": True, "rate": payload["rate"], "source": source, "date": payload["date"]}

    def fetch_external_rate(self) -> float:
        """Intenta obtener la tasa BCV desde APIs públicas (no se muestra en UI)."""
        # 1) Si el usuario configuró su propio endpoint (ideal)
        if settings.bcv_api_url:
            try:
                res = requests.get(settings.bcv_api_url, timeout=8)
                if res.ok:
                    data = res.json()
                    # intenta mapeos comunes
                    for key in ("bcv", "BCV", "price", "valor", "rate"):
                        if isinstance(data, dict) and key in data and float(data[key]) > 0:
                            return float(data[key])
                    # algunos devuelven {monitors:{bcv:{price}}}
                    if "monitors" in data and "bcv" in data["monitors"]:
                        return float(data["monitors"]["bcv"]["price"])
            except Exception:
                pass

        # 2) Proveedores comunitarios (no oficiales, pero suelen reflejar BCV)
        providers = [
    ("https://open.er-api.com/v6/latest/USD", lambda j: float(j["rates"]["VES"])),
]

        for url, extractor in providers:
            try:
                res = requests.get(url, timeout=8)
                if res.ok:
                    rate = extractor(res.json())
                    if rate and rate > 0:
                        return float(rate)
            except Exception:
                continue

        # 3) Respaldo (env) si todo falla
        return settings.default_usdves_rate

    # ===== Config pública (no expone tasa) =====
    def public_config(self) -> Dict[str, Any]:
        raffle = self.get_current_raffle(raise_if_missing=False)
        usd_price = cents_to_usd(raffle["ticket_price_cents"]) if raffle else None
        currency = raffle["currency"] if raffle else "USD"

        ves_per_ticket = None
        if usd_price is not None:
            rate = self.get_rate()  # se usa solo para calcular, no se devuelve
            ves_per_ticket = round(usd_price * rate, 2)

        return {
            "raffle_active": bool(raffle),
            "raffle_name": raffle["name"] if raffle else None,
            "currency": currency,                 # p.ej. "USD"
            "usd_price": usd_price,               # precio por ticket en USD
            "ves_price_per_ticket": ves_per_ticket,  # precio por ticket en Bs (con tasa oculta)
            "pagomovil_info": settings.pagomovil_info,
            "payments_bucket": settings.payments_bucket,
            "supabase_url": settings.supabase_url,
            "public_anon_key": settings.public_anon_key,
        }

    # ===== Tickets =====
    def reserve_tickets(self, email: str, quantity: int) -> List[Dict[str, Any]]:
        if quantity < 1:
            raise ValueError("quantity debe ser >= 1")
        raffle = self.get_current_raffle()
        rows = [{"raffle_id": raffle["id"], "email": email, "status": "reserved"} for _ in range(quantity)]
        resp = self.client.table("tickets").insert(rows).select("id, number").execute()
        if not resp.data:
            raise RuntimeError("No se pudieron crear los tickets")
        return resp.data

    def mark_paid(self, ticket_ids: List[str], payment_ref: str):
        if not ticket_ids:
            return
        self.client.table("tickets").update({"status": "paid", "payment_ref": payment_ref}).in_("id", ticket_ids).execute()

    # ===== Pago Móvil =====
    def create_mobile_payment(self, email: str, quantity: int, reference: str, evidence_url: Optional[str]) -> Dict[str, Any]:
        if quantity < 1:
            raise ValueError("quantity debe ser >= 1")
        raffle = self.get_current_raffle()
        tickets = self.reserve_tickets(email, quantity)
        ticket_ids = [t["id"] for t in tickets]

        usd_price = cents_to_usd(raffle["ticket_price_cents"])
        rate = self.get_rate()
        usd_amount = round(usd_price * quantity, 2)
        ves_amount = round(usd_amount * rate, 2)

        pay = {
            "raffle_id": raffle["id"],
            "email": email,
            "quantity": quantity,
            "usd_amount": usd_amount,
            "ves_rate": rate,   # se guarda en DB para auditoría, pero no se expone en /config
            "ves_amount": ves_amount,
            "reference": reference,
            "evidence_url": evidence_url,
            "status": "pending",
        }
        presp = self.client.table("payments").insert(pay).select("id").execute()
        payment_id = presp.data[0]["id"]
        links = [{"payment_id": payment_id, "ticket_id": tid} for tid in ticket_ids]
        self.client.table("payment_tickets").insert(links).execute()
        return {
            "payment_id": payment_id, "tickets": tickets,
            "usd_amount": usd_amount, "ves_amount": ves_amount,
            "status": "pending"
        }

    # ===== Admin =====
    def admin_verify_payment(self, payment_id: str, approve: bool) -> Dict[str, Any]:
        links = self.client.table("payment_tickets").select("ticket_id").eq("payment_id", payment_id).execute()
        ticket_ids = [x["ticket_id"] for x in (links.data or [])]
        if approve:
            paydata = self.client.table("payments").select("reference").eq("id", payment_id).single().execute().data
            ref = paydata["reference"] if paydata else f"PAY-{payment_id}"
            self.mark_paid(ticket_ids, ref)
            self.client.table("payments").update({"status": "verified"}).eq("id", payment_id).execute()
            return {"payment_id": payment_id, "status": "verified", "ticket_ids": ticket_ids}
        else:
            self.client.table("payments").update({"status": "rejected"}).eq("id", payment_id).execute()
            return {"payment_id": payment_id, "status": "rejected", "ticket_ids": ticket_ids}

    # ===== Sorteo =====
    def start_draw(self, seed: Optional[int]) -> str:
        raffle = self.get_current_raffle()
        resp = self.client.table("draws").insert({"raffle_id": raffle["id"], "seed": seed}).execute()
        if not resp.data:
            raise RuntimeError("No se pudo iniciar el sorteo")
        return resp.data[0]["id"]

    def get_latest_draw_for_current_raffle(self) -> Optional[Dict[str, Any]]:
        raffle = self.get_current_raffle()
        r = (self.client.table("draws")
             .select("id, raffle_id, started_at")
             .eq("raffle_id", raffle["id"])
             .order("started_at", desc=True)
             .limit(1).execute())
        return r.data[0] if r.data else None

    def pick_winners(self, draw_id: str, n: int, unique: bool = True) -> List[Dict[str, Any]]:
        raffle = self.get_current_raffle()
        paid = (self.client.table("tickets")
                .select("id, number, email")
                .eq("raffle_id", raffle["id"])
                .eq("status", "paid")
                .order("number")
                .execute())
        records = paid.data or []
        if not records:
            return []
        rng = random.Random()
        pool = list(records)
        chosen = pool[:n] if unique else [rng.choice(pool) for _ in range(n)]
        if unique:
            rng.shuffle(chosen)
        rows = [{"draw_id": draw_id, "raffle_id": raffle["id"], "ticket_id": c["id"], "position": i+1}
                for i, c in enumerate(chosen)]
        inserted = self.client.table("winners").insert(rows).select("id, position, ticket_id").execute().data
        by_tid = {c["id"]: c for c in chosen}
        return [{"winner_id": w["id"], "position": w["position"], "ticket_id": w["ticket_id"],
                 "ticket_number": by_tid[w["ticket_id"]]["number"],
                 "email_masked": _mask_email(by_tid[w["ticket_id"]]["email"])} for w in inserted]
