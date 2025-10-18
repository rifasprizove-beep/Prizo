from typing import List, Optional, Any, Dict
from pydantic import BaseModel, EmailStr, Field, root_validator


# ---------- RESERVAS ----------
class ReserveRequest(BaseModel):
    email: EmailStr
    # Modo 1: reservar N tickets libres
    quantity: int = Field(1, ge=1, description="Cantidad de tickets a reservar (>=1)")
    raffle_id: Optional[str] = None

    # Modo 2: reservar por IDs de tickets existentes
    ticket_ids: Optional[List[str]] = Field(
        default=None, description="IDs de tickets a reservar"
    )

    # Modo 3: reservar por números de ticket
    ticket_numbers: Optional[List[int]] = Field(
        default=None, description="Números de ticket a reservar"
    )

    @root_validator
    def validate_reserve_mode(cls, values):
        """
        Acepta cualquiera de los tres modos, pero al menos uno debe estar activo:
        - quantity >= 1 (por defecto 1), o
        - ticket_ids con elementos, o
        - ticket_numbers con elementos.
        Si se usan listas, deben venir no vacías.
        """
        qty = values.get("quantity", 0)
        ids = values.get("ticket_ids")
        nums = values.get("ticket_numbers")

        has_ids = isinstance(ids, list) and len(ids) > 0
        has_nums = isinstance(nums, list) and len(nums) > 0
        has_qty = isinstance(qty, int) and qty >= 1

        if not (has_qty or has_ids or has_nums):
            raise ValueError(
                "Debe indicar 'quantity' >= 1 o bien 'ticket_ids' o 'ticket_numbers' con elementos."
            )
        return values


class ReserveResponse(BaseModel):
    tickets: List[Dict[str, Any]]


# ---------- MARCAR PAGADO ----------
class MarkPaidRequest(BaseModel):
    ticket_ids: List[str] = Field(..., min_items=1)
    payment_ref: str = Field(..., min_length=1)


# ---------- SORTEO ----------
class DrawStartRequest(BaseModel):
    seed: Optional[int] = None


class DrawStartResponse(BaseModel):
    draw_id: str


class DrawPickRequest(BaseModel):
    draw_id: Optional[str] = None
    n: int = Field(1, ge=1)
    unique: bool = True


# ---------- PAGOS ----------
class PaymentRequest(BaseModel):
    email: EmailStr
    quantity: int = Field(..., ge=1)
    reference: str = Field(..., min_length=1)
    evidence_url: Optional[str] = None
    method: Optional[str] = None
    raffle_id: Optional[str] = None

    # Datos de comprador
    document_id: Optional[str] = None
    state: Optional[str] = None
    phone: Optional[str] = None  # NUEVO


class SubmitReservedRequest(BaseModel):
    email: EmailStr
    ticket_ids: List[str] = Field(..., min_items=1)
    reference: str = Field(..., min_length=1)
    evidence_url: Optional[str] = None
    method: Optional[str] = None
    raffle_id: Optional[str] = None

    # Datos de comprador
    document_id: Optional[str] = None
    state: Optional[str] = None
    phone: Optional[str] = None  # NUEVO


# ---------- CONSULTAS / COTIZACIÓN ----------
class VerifyAdminRequest(BaseModel):
    payment_id: str
    approve: bool


class CheckRequest(BaseModel):
    ticket_number: Optional[int] = None
    reference: Optional[str] = None
    email: Optional[EmailStr] = None


class QuoteRequest(BaseModel):
    quantity: int = Field(..., ge=1)
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
