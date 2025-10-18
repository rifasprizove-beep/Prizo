from typing import List, Optional, Any, Dict
from pydantic import BaseModel, EmailStr, model_validator

# ---------- Reservas ----------
class ReserveRequest(BaseModel):
    email: EmailStr
    quantity: int = 1
    raffle_id: Optional[str] = None
    # Modos alternativos del endpoint /tickets/reserve
    ticket_ids: Optional[List[str]] = None
    ticket_numbers: Optional[List[int]] = None

    @model_validator(mode="after")
    def _validate_choice(self):
        """
        Reglas:
        - Puedes enviar {ticket_ids} o {ticket_numbers} o {quantity}; pero no ambos ids y numbers a la vez.
        - Si NO envías ni ids ni numbers, entonces quantity debe ser >= 1.
        - Si envías ids o numbers, quantity se ignora.
        """
        if self.ticket_ids and self.ticket_numbers:
            raise ValueError("Usa 'ticket_ids' o 'ticket_numbers', no ambos.")

        if not (self.ticket_ids or self.ticket_numbers):
            if not self.quantity or self.quantity < 1:
                raise ValueError(
                    "quantity debe ser >= 1 cuando no envías 'ticket_ids' ni 'ticket_numbers'."
                )
        return self


class ReserveResponse(BaseModel):
    tickets: List[Dict[str, Any]]


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
