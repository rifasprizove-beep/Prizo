from __future__ import annotations
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple
import os
import time
import uuid

# NOTE: Minimal fallback implementation so the API boots on Render.
# Replace with your real Supabase-backed logic when ready.


@dataclass
class Settings:
    # Admin/API
    admin_api_key: str = os.getenv("ADMIN_API_KEY", "")

    # Public client (for frontend uploads if needed)
    supabase_url: str = os.getenv("SUPABASE_URL", "")
    public_anon_key: str = os.getenv("SUPABASE_ANON_KEY", "")

    # Storage bucket where payment receipts would go (frontend might reference it)
    payments_bucket: str = os.getenv("PAYMENTS_BUCKET", "payments")

    # Default pricing/currency (simple demo)
    currency: str = os.getenv("CURRENCY", "USD")
    usd_price: float = float(os.getenv("USD_PRICE", "1.0"))  # precio unitario en USD para demo

    # Demo Pago Móvil info (shown in /config)
    pagomovil_info: Dict[str, str] = field(default_factory=lambda: {
        "Banco": os.getenv("PM_BANK", "Banesco"),
        "Teléfono": os.getenv("PM_PHONE", "0414-1234567"),
        "Cédula/RIF": os.getenv("PM_ID", "V-12.345.678"),
        "Titular": os.getenv("PM_HOLDER", "PRIZO"),
        "Tipo": "Pago Móvil",
    })


settings = Settings()


def make_client() -> Any:
    """
    Fallback: return a placeholder client. Real implementation should
    create and return a Supabase client using supabase-py.
    """
    return {"client": "stub"}


class RaffleService:
    """
    Minimal, in-memory service to keep the API running. Data resets on restart.
    Replace all methods with real implementations when your DB layer is ready.
    """

    def __init__(self, client: Any):
        self.client = client
        self._rate: float = float(os.getenv("VES_RATE", "45.0"))  # demo rate VES/USD
        self._raffles: Dict[str, Dict[str, Any]] = {}
        self._tickets_by_raffle: Dict[str, List[Dict[str, Any]]] = {}
        self._payments: Dict[str, Dict[str, Any]] = {}
        self._draws: Dict[str, Dict[str, Any]] = {}

        # Seed one demo raffle so UI doesn't look empty
        self._ensure_demo_raffle()

    # ------------- Helpers -------------
    def _ensure_demo_raffle(self):
        if not self._raffles:
            rid = str(uuid.uuid4())
            self._raffles[rid] = {
                "id": rid,
                "name": os.getenv("DEMO_RAFFLE_NAME", "Rifa Demo"),
                "image_url": os.getenv("DEMO_RAFFLE_IMAGE", "https://picsum.photos/1024/576"),
                "active": True,
                "total_tickets": 1000,
                "usd_price": settings.usd_price,
                "created_at": time.time(),
            }
            self._tickets_by_raffle[rid] = []

    def _active_raffle(self) -> Optional[Dict[str, Any]]:
        for r in self._raffles.values():
            if r.get("active"):
                return r
        return None

    # ------------- Salud / Config -------------
    def get_current_raffle(self, raise_if_missing: bool = True) -> Optional[Dict[str, Any]]:
        r = self._active_raffle()
        if not r and raise_if_missing:
            raise RuntimeError("No hay rifa activa")
        return r

    def public_config(self, raffle_id: Optional[str] = None) -> Dict[str, Any]:
        r = self.get_raffle_by_id(raffle_id) or self._active_raffle()
        if not r:
            # Minimal config if nothing is active
            return {
                "raffle_active": False,
                "raffle_id": None,
                "raffle_name": None,
                "image_url": None,
                "currency": settings.currency,
                "usd_price": None,
                "payment_methods": {
                    "pago_movil": settings.pagomovil_info,
                },
                "progress": {},
            }

        progress = self.progress_for_public(r)
        return {
            "raffle_active": True,
            "raffle_id": r["id"],
            "raffle_name": r["name"],
            "image_url": r.get("image_url"),
            "currency": settings.currency,
            "usd_price": r.get("usd_price"),
            "payment_methods": {
                "pago_movil": settings.pagomovil_info,
            },
            "progress": progress,
        }

    # ------------- Rifas -------------
    def list_open_raffles(self) -> List[Dict[str, Any]]:
        return [r for r in self._raffles.values() if r.get("active")]

    def get_raffle_by_id(self, raffle_id: Optional[str]) -> Optional[Dict[str, Any]]:
        if not raffle_id:
            return None
        return self._raffles.get(raffle_id)

    def progress_for_public(self, raffle: Dict[str, Any]) -> Dict[str, Any]:
        r_id = raffle["id"]
        sold = sum(1 for t in self._tickets_by_raffle.get(r_id, []) if t.get("status") == "paid")
        total = raffle.get("total_tickets", 0)
        remain = max(total - sold, 0)
        pct = (sold / total * 100) if total else 0
        return {
            "sold": sold,
            "total": total,
            "remain": remain,
            "pct": round(pct, 2),
        }

    # ------------- Tasa -------------
    def get_rate_info(self) -> Dict[str, Any]:
        return {"rate": self._rate, "currency": settings.currency, "updated_at": time.time()}

    def set_rate(self, rate: float, source: str = "manual") -> Dict[str, Any]:
        self._rate = float(rate)
        return {"rate": self._rate, "source": source, "updated_at": time.time()}

    def fetch_external_rate(self) -> float:
        # Fallback: return the current rate without external calls
        return self._rate

    # ------------- Cotización -------------
    def _usd_totals(self, quantity: int, raffle: Dict[str, Any]) -> Tuple[float, float]:
        unit = float(raffle.get("usd_price") or settings.usd_price or 1.0)
        total = unit * int(quantity)
        return unit, total

    def quote_amount(self, quantity: int, raffle_id: Optional[str], method: str, usd_only: bool = False) -> Dict[str, Any]:
        r = self.get_raffle_by_id(raffle_id) or self.get_current_raffle()
        if not r:
            raise RuntimeError("No hay rifa activa")
        unit_usd, total_usd = self._usd_totals(quantity, r)
        if usd_only or settings.currency.upper() == "USD":
            return {
                "raffle_id": r["id"],
                "method": method,
                "unit_price_usd": unit_usd,
                "total_usd": total_usd,
            }
        # VES
        ves_rate = self._rate
        return {
            "raffle_id": r["id"],
            "method": method,
            "unit_price_usd": unit_usd,
            "total_usd": total_usd,
            "unit_price_ves": round(unit_usd * ves_rate, 2),
            "total_ves": round(total_usd * ves_rate, 2),
        }

    # ------------- Tickets / Pagos -------------
    def reserve_tickets(self, email: str, quantity: int, raffle_id: Optional[str] = None) -> List[Dict[str, Any]]:
        r = self.get_raffle_by_id(raffle_id) or self.get_current_raffle()
        if not r:
            raise RuntimeError("No hay rifa activa")
        r_id = r["id"]
        q = max(int(quantity), 1)
        allocated = []
        next_number = len(self._tickets_by_raffle[r_id]) + 1
        for _ in range(q):
            t_id = str(uuid.uuid4())
            ticket = {
                "id": t_id,
                "raffle_id": r_id,
                "email": email,
                "number": next_number,
                "status": "reserved",
                "created_at": time.time(),
            }
            self._tickets_by_raffle[r_id].append(ticket)
            allocated.append(ticket)
            next_number += 1
        return allocated

    def mark_paid(self, ticket_ids: List[str], payment_ref: str) -> None:
        for tickets in self._tickets_by_raffle.values():
            for t in tickets:
                if t["id"] in ticket_ids:
                    t["status"] = "paid"
                    t["payment_ref"] = payment_ref

    def create_mobile_payment(self, email: str, quantity: int, reference: str, evidence_url: Optional[str], raffle_id: Optional[str], method: Optional[str]):
        # Reserve tickets and mark as paid for demo purposes
        tickets = self.reserve_tickets(email, quantity, raffle_id)
        self.mark_paid([t["id"] for t in tickets], reference)
        p_id = str(uuid.uuid4())
        self._payments[p_id] = {
            "id": p_id,
            "email": email,
            "reference": reference,
            "evidence_url": evidence_url,
            "tickets": [t["id"] for t in tickets],
            "created_at": time.time(),
            "status": "pending_review",
        }
        return {"payment_id": p_id, "tickets": tickets}

    def admin_verify_payment(self, payment_id: str, approve: bool):
        p = self._payments.get(payment_id)
        if not p:
            raise RuntimeError("Pago no encontrado")
        p["status"] = "approved" if approve else "rejected"
        return {"ok": True, "status": p["status"]}

    def check_status(self, ticket_number: Optional[int], reference: Optional[str], email: Optional[str]):
        # Simple search across in-memory data
        results: List[Dict[str, Any]] = []
        for tickets in self._tickets_by_raffle.values():
            for t in tickets:
                if ticket_number and t.get("number") == int(ticket_number):
                    results.append(t)
                elif email and t.get("email") == email:
                    results.append(t)
        if reference:
            for p in self._payments.values():
                if p.get("reference") == reference:
                    results.append({"payment": p})
        return {"results": results}

    # ------------- Sorteo -------------
    def start_draw(self, seed: Optional[int] = None) -> str:
        d_id = str(uuid.uuid4())
        self._draws[d_id] = {"id": d_id, "seed": seed, "created_at": time.time()}
        return d_id

    def get_latest_draw_for_current_raffle(self) -> Optional[Dict[str, Any]]:
        if not self._draws:
            return None
        # Return the most recent by created_at
        return sorted(self._draws.values(), key=lambda d: d["created_at"], reverse=True)[0]

    def pick_winners(self, draw_id: str, n: int, unique: bool) -> List[Dict[str, Any]]:
        # For demo: choose among all PAID tickets in the active raffle
        r = self.get_current_raffle(raise_if_missing=False)
        if not r:
            return []
        pool = [t for t in self._tickets_by_raffle.get(r["id"], []) if t.get("status") == "paid"]
        if not pool:
            return []
        # Simple deterministic pick: slice first n (since we avoid random without CSV here)
        winners = pool[: max(n, 1)] if unique else (pool * n)[:n]
        return [{"ticket_number": w["number"], "email": w["email"]} for w in winners]
