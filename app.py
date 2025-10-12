import os
from typing import List, Optional, Any, Dict
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr

from logic import RaffleService, make_client, settings

app = FastAPI(title="Raffle Pro API", version="2.3.1")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
else:
    print("[WARN] 'static/' no existe; se salta el montaje.")

client = make_client()
svc = RaffleService(client)

# -------- modelos --------
class ReserveRequest(BaseModel):
    email: EmailStr
    quantity: int = 1
    raffle_id: Optional[str] = None

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
    method: Optional[str] = "pago_movil"

class QuoteResponse(BaseModel):
    raffle_id: Optional[str]
    method: str
    unit_price_usd: Optional[float]
    total_usd: Optional[float]
    unit_price_ves: Optional[float] = None
    total_ves: Optional[float] = None

USD_ONLY = {"binance", "zinli", "zelle"}

def require_admin(x_admin_key: str = Header(default="")):
    if not settings.admin_api_key or x_admin_key != settings.admin_api_key:
        raise HTTPException(401, "Admin key inválida")

def _validate_quantity(q: int):
    if q < 1 or q > 50:
        raise HTTPException(400, "Cantidad inválida (1–50)")

# -------- salud / config --------
@app.get("/health")
def health():
    try:
        raffle = svc.get_current_raffle(raise_if_missing=False)
        return {"status": "ok", "active_raffle": bool(raffle)}
    except Exception as e:
        return {"status": "degraded", "error": str(e)}

@app.get("/config")
def public_config(raffle_id: Optional[str] = Query(default=None)):
    """
    Devuelve configuración pública. Nunca rompe el front:
    si ocurre algo, devuelve valores seguros.
    """
    try:
        cfg = svc.public_config(raffle_id=raffle_id)
        # blindaje mínimo para el front
        base = {
            "raffle_active": False,
            "raffle_id": None,
            "raffle_name": None,
            "image_url": None,
            "currency": "USD",
            "usd_price": None,
            "ves_price_per_ticket": 0.0,
            "pagomovil_info": settings.pagomovil_info,
            "payments_bucket": settings.payments_bucket,
            "supabase_url": settings.supabase_url,
            "public_anon_key": settings.public_anon_key,
        }
        base.update(cfg or {})
        return base
    except Exception as e:
        # 200 con defaults para que el front pueda seguir
        return {
            "raffle_active": False,
            "raffle_id": None,
            "raffle_name": None,
            "image_url": None,
            "currency": "USD",
            "usd_price": None,
            "ves_price_per_ticket": 0.0,
            "pagomovil_info": settings.pagomovil_info,
            "payments_bucket": settings.payments_bucket,
            "supabase_url": settings.supabase_url,
            "public_anon_key": settings.public_anon_key,
            "error": f"/config fallback: {str(e)}",
        }

# -------- rifas --------
@app.get("/raffles/list")
def raffles_list():
    try:
        return {"raffles": svc.list_open_raffles()}
    except Exception as e:
        return {"raffles": [], "error": str(e)}

# -------- tasa --------
@app.get("/rate/current")
def get_current_rate():
    return svc.get_rate_info()

@app.post("/admin/rate/set")
def set_rate(body: Dict[str, float], x_admin_key: str = Header(default="")):
    require_admin(x_admin_key)
    rate = float(body.get("rate"))
    return svc.set_rate(rate, source="manual")

@app.post("/admin/rate/update")
def update_rate(x_admin_key: str = Header(default="")):
    require_admin(x_admin_key)
    rate = svc.fetch_external_rate()
    return svc.set_rate(rate, source="auto")

# -------- cotización --------
@app.post("/quote", response_model=QuoteResponse)
def quote_amount(req: QuoteRequest):
    _validate_quantity(req.quantity)
    method = (req.method or "pago_movil").strip().lower()
    try:
        data = svc.quote_amount(
            quantity=req.quantity,
            raffle_id=req.raffle_id,
            method=method,
            usd_only=(method in USD_ONLY),
        )
        return data
    except Exception as e:
        # 400 informativo (el front ya muestra mensaje)
        raise HTTPException(status_code=400, detail=str(e))

# -------- tickets / pagos --------
@app.post("/tickets/reserve", response_model=ReserveResponse)
def reserve(req: ReserveRequest):
    _validate_quantity(req.quantity)
    return {"tickets": svc.reserve_tickets(req.email, req.quantity, raffle_id=req.raffle_id)}

@app.post("/tickets/paid")
def mark_paid(req: MarkPaidRequest):
    svc.mark_paid(req.ticket_ids, req.payment_ref)
    return {"ok": True}

@app.post("/payments/submit")
def submit_payment_unified(req: PaymentRequest):
    _validate_quantity(req.quantity)
    method = (req.method or "").strip().lower() or None
    try:
        data = svc.create_mobile_payment(
            req.email,
            req.quantity,
            req.reference,
            req.evidence_url,
            raffle_id=req.raffle_id,
            method=method,
        )
        return {"message": "Pago registrado. Verificación 24–72h.", **data}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/payments/verify")
def verify_payment(req: VerifyAdminRequest, x_admin_key: str = Header(default="")):
    require_admin(x_admin_key)
    return svc.admin_verify_payment(req.payment_id, req.approve)

@app.post("/tickets/check")
def check_status(req: CheckRequest):
    return svc.check_status(req.ticket_number, req.reference, req.email)

# -------- sorteo --------
@app.post("/draw/start", response_model=DrawStartResponse)
def draw_start(req: DrawStartRequest):
    draw_id = svc.start_draw(req.seed)
    return {"draw_id": draw_id}

@app.post("/draw/pick")
def draw_pick(req: DrawPickRequest):
    if req.n < 1:
        raise HTTPException(400, "n debe ser >= 1")
    draw_id = req.draw_id
    if not draw_id or draw_id == "current":
        draw = svc.get_latest_draw_for_current_raffle()
        if not draw:
            draw_id = svc.start_draw(seed=None)
        else:
            draw_id = draw["id"]
    winners = svc.pick_winners(draw_id, req.n, req.unique)
    return {"winners": winners}

# -------- front --------
@app.get("/")
def index(request: Request):
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return {"message": "Sube tu frontend en /static (index.html)"}
