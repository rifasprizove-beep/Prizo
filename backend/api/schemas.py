from typing import List, Optional, Any, Dict
from pydantic import BaseModel, EmailStr, model_validator

# ---------- Reservas ----------
# ReserveRequest: ahora SIN email
class ReserveRequest(BaseModel):
    raffle_id: Optional[str] = None
    quantity: int = 1

# ReserveResponse: incluye hold_id
class ReserveResponse(BaseModel):
    hold_id: str
    tickets: List[Dict[str, Any]]

# SubmitReservedRequest: ahora requiere hold_id
class SubmitReservedRequest(BaseModel):
    raffle_id: Optional[str] = None
    ticket_ids: List[str]
    reference: str
    evidence_url: Optional[str] = None
    method: Optional[str] = "pago_movil"
    # datos del comprador (se guardan recién aquí)
    email: EmailStr
    document_id: Optional[str] = None
    state: Optional[str] = None
    phone: Optional[str] = None
    # token anónimo de reserva
    hold_id: str



class MarkPaidRequest(BaseModel):
    ticket_ids: List[str]
    payment_ref: str


# ---------- Sorteo ----------
class DrawStartRequest(BaseModel):
    seed: Optional[int] = None


class DrawStartResponse(BaseModel):
    draw_id: str


class DrawPickRequest(BaseModel):
    draw_id: Optional[str] = None
    n: int = 1
    unique: bool = True


# ---------- Pagos ----------
class PaymentRequest(BaseModel):
    email: EmailStr
    quantity: int
    reference: str
    evidence_url: Optional[str] = None
    method: Optional[str] = None
    raffle_id: Optional[str] = None
    document_id: Optional[str] = None
    state: Optional[str] = None
    phone: Optional[str] = None  # NUEVO


class SubmitReservedRequest(BaseModel):
    email: EmailStr
    ticket_ids: List[str]
    reference: str
    evidence_url: Optional[str] = None
    method: Optional[str] = None
    raffle_id: Optional[str] = None
    document_id: Optional[str] = None
    state: Optional[str] = None
    phone: Optional[str] = None  # NUEVO


# ---------- Admin ----------
class VerifyAdminRequest(BaseModel):
    payment_id: str
    approve: bool


# ---------- Consultas ----------
class CheckRequest(BaseModel):
    ticket_number: Optional[int] = None
    reference: Optional[str] = None
    email: Optional[EmailStr] = None


# ---------- Cotización ----------
class QuoteRequest(BaseModel):
    quantity: int
    raffle_id: Optional[str] = None
    method: str = "pago_movil"  # default directo


class QuoteResponse(BaseModel):
    raffle_id: Optional[str]
    method: str
    unit_price_usd: Optional[float]
    total_usd: Optional[float]
    unit_price_ves: Optional[float] = None
    total_ves: Optional[float] = None
    error: Optional[str] = None
