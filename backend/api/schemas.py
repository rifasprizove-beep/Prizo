# backend/api/schemas.py
from typing import Optional, Any, Dict, List
from pydantic import BaseModel, EmailStr

# -------- Reservas --------
class ReserveRequest(BaseModel):
    raffle_id: Optional[str] = None
    quantity: int = 1  # reserva anónima por cantidad
    ticket_ids: Optional[List[str]] = None
    ticket_numbers: Optional[List[int]] = None


class ReserveResponse(BaseModel):
    hold_id: str
    tickets: List[Dict[str, Any]]

# -------- Pagos --------
class SubmitReservedRequest(BaseModel):
    raffle_id: Optional[str] = None
    ticket_ids: List[str]
    reference: str
    evidence_url: Optional[str] = None
    method: Optional[str] = "pago_movil"
    # datos del comprador (recién al pagar)
    email: EmailStr
    document_id: Optional[str] = None
    state: Optional[str] = None
    phone: Optional[str] = None
    # token anónimo que devuelve /tickets/reserve
    hold_id: str

# JSON alternativo usado por /payments/submit (compat)
class PaymentRequest(BaseModel):
    raffle_id: Optional[str] = None
    email: EmailStr
    quantity: int
    reference: str
    evidence_url: Optional[str] = None
    method: Optional[str] = "pago_movil"
    document_id: Optional[str] = None
    state: Optional[str] = None
    phone: Optional[str] = None

class MarkPaidRequest(BaseModel):
    ticket_ids: List[str]
    payment_ref: str

# -------- Tasa / Cotización --------
class QuoteRequest(BaseModel):
    raffle_id: Optional[str] = None
    quantity: int
    method: Optional[str] = "pago_movil"

class QuoteResponse(BaseModel):
    raffle_id: Optional[str]
    method: str
    unit_price_usd: Optional[float]
    total_usd: Optional[float]
    unit_price_ves: Optional[float]
    total_ves: Optional[float]
    error: Optional[str] = None

# -------- Sorteo --------
class DrawStartRequest(BaseModel):
    seed: Optional[int] = None

class DrawStartResponse(BaseModel):
    draw_id: str

class DrawPickRequest(BaseModel):
    draw_id: Optional[str] = "current"
    n: int
    unique: bool = True

# -------- Admin --------
class VerifyAdminRequest(BaseModel):
    payment_id: str
    approve: bool

# -------- Consultas --------
class CheckRequest(BaseModel):
    ticket_number: Optional[int] = None
    reference: Optional[str] = None
    email: Optional[EmailStr] = None
