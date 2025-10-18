from typing import List, Optional, Any, Dict 
from pydantic import BaseModel, EmailStr

class ReserveRequest(BaseModel):
    email: EmailStr
    quantity: int = 1
    raffle_id: Optional[str] = None
    # NUEVO: soporta los otros modos del endpoint /tickets/reserve
    ticket_ids: Optional[List[str]] = None
    ticket_numbers: Optional[List[int]] = None

class ReserveResponse(BaseModel):
    tickets: List[Dict[str, Any]]

class MarkPaidRequest(BaseModel):
    ticket_ids: List[str]
    payment_ref: str

class DrawStartRequest(BaseModel):
    seed: Optional[int] = None

class DrawStartResponse(BaseModel):
    draw_id: str

class DrawPickRequest(BaseModel):
    draw_id: Optional[str] = None
    n: int = 1
    unique: bool = True

class PaymentRequest(BaseModel):
    email: EmailStr
    quantity: int
    reference: str
    evidence_url: Optional[str] = None
    method: Optional[str] = None
    raffle_id: Optional[str] = None
    document_id: Optional[str] = None
    state: Optional[str] = None

class SubmitReservedRequest(BaseModel):
    email: EmailStr
    ticket_ids: List[str]
    reference: str
    evidence_url: Optional[str] = None
    method: Optional[str] = None
    raffle_id: Optional[str] = None
    document_id: Optional[str] = None
    state: Optional[str] = None

class VerifyAdminRequest(BaseModel):
    payment_id: str
    approve: bool

class CheckRequest(BaseModel):
    ticket_number: Optional[int] = None
    reference: Optional[str] = None
    email: Optional[EmailStr] = None

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
