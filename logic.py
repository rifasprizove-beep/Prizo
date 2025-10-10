# logic.py
from __future__ import annotations
import random
from typing import List, Optional, Dict, Any
from os import getenv
from pydantic import BaseModel
from supabase import create_client, Client

# ---------- Settings ----------
class Settings(BaseModel):
    supabase_url: str = getenv("SUPABASE_URL", "")
    supabase_service_key: str = getenv("SUPABASE_SERVICE_KEY", "")
    public_anon_key: str = getenv("PUBLIC_SUPABASE_ANON_KEY", "")
    raffle_id: str = getenv("RAFFLE_ID", "")
    currency: str = getenv("CURRENCY", "USD")
    ticket_price_cents: int = int(getenv("TICKET_PRICE_CENTS", "1000"))

settings = Settings()

def make_client() -> Client:
    if not settings.supabase_url or not settings.supabase_service_key:
        raise RuntimeError("Faltan SUPABASE_URL o SUPABASE_SERVICE_KEY")
    return create_client(settings.supabase_url, settings.supabase_service_key)

def _mask_email(email: str) -> str:
    """Enmascara emails tipo ju***@do***.com"""
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

# ---------- Servicio de Rifa ----------
class RaffleService:
    """
    Usa tablas Supabase:
      - tickets(id, raffle_id, email, number, status, payment_ref)
      - draws(id, raffle_id, seed)
      - winners(id, draw_id, raffle_id, ticket_id, position)
    """
    def __init__(self, client: Client, raffle_id: str):
        if not raffle_id:
            raise RuntimeError("Falta RAFFLE_ID")
        self.client = client
        self.raffle_id = raffle_id

    # ---- Tickets ----
    def reserve_tickets(self, email: str, quantity: int) -> List[Dict[str, Any]]:
        if quantity < 1:
            raise ValueError("quantity debe ser >= 1")
        rows = [{
            "raffle_id": self.raffle_id,
            "email": email,
            "status": "reserved",
        } for _ in range(quantity)]
        resp = self.client.table("tickets").insert(rows).select("id, number").execute()
        if not hasattr(resp, "data") or not resp.data:
            raise RuntimeError("No se pudieron crear los tickets")
        return resp.data

    def mark_paid(self, ticket_ids: List[str], payment_ref: str):
        if not ticket_ids:
            return
        self.client.table("tickets") \
            .update({"status": "paid", "payment_ref": payment_ref}) \
            .in_("id", ticket_ids) \
            .execute()

    # ---- Sorteo ----
    def start_draw(self, seed: Optional[int]) -> str:
        payload = {"raffle_id": self.raffle_id, "seed": seed}
        resp = self.client.table("draws").insert(payload).execute()
        if not resp.data:
            raise RuntimeError("No se pudo iniciar el sorteo")
        return resp.data[0]["id"]

    def pick_winners(self, draw_id: str, n: int, unique: bool = True) -> List[Dict[str, Any]]:
        if n < 1:
            raise ValueError("n debe ser >= 1")
        paid = (self.client.table("tickets")
                .select("id, number, email")
                .eq("raffle_id", self.raffle_id)
                .eq("status", "paid")
                .order("number")
                .execute())
        records = paid.data or []
        if not records:
            return []
        rng = random.Random()
        pool = list(records)
        if unique:
            rng.shuffle(pool)
            chosen = pool[:n]
        else:
            chosen = [rng.choice(pool) for _ in range(n)]
        rows = [{
            "draw_id": draw_id,
            "raffle_id": self.raffle_id,
            "ticket_id": c["id"],
            "position": i + 1,
        } for i, c in enumerate(chosen)]
        inserted = self.client.table("winners").insert(rows).select("id, position, ticket_id").execute().data
        by_tid = {c["id"]: c for c in chosen}
        out: List[Dict[str, Any]] = []
        for w in inserted:
            t = by_tid.get(w["ticket_id"], {})
            out.append({
                "winner_id": w["id"],
                "position": w["position"],
                "ticket_id": w["ticket_id"],
                "ticket_number": t.get("number"),
                "email_masked": _mask_email(t.get("email", "")),
            })
        return out

    def finish_draw(self, draw_id: str):
        self.client.table("draws").update({"finished_at": "now()"}).eq("id", draw_id).execute()
