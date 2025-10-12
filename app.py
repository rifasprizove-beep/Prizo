import os
from typing import List, Optional, Any, Dict
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr

from logic import RaffleService, make_client, settings

app = FastAPI(title="Raffle Pro API", version="2.3.0")

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

# -------- modelos (manteniendo estructura; añado modelos de cotización) --------
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
    method: Optional[str] = None  # compatibilidad con el front
    raffle_id: Optional[str] = None

class VerifyAdminRequest(BaseModel):
    payment_id: str
    approve: bool

class CheckRequest(BaseModel):
    ticket_number: Optional[int] = None
    reference: Optional[str] = None
    email: Optional[EmailStr] = None

# --- Nuevos modelos para cotización ---
class QuoteRequest(BaseModel):
    quantity: int
    raffle_id: Optional[str] = None
    method: Optional[str] = "pago_movil"  # pago_movil, transferencia, zelle, binance, zinli, etc.

class QuoteResponse(BaseModel):
    raffle_id: str
    method: str
    unit_price_usd: float
    total_usd: float
    unit_price_ves: Optional[float] = None
    total_ves: Optional[float] = None
    # Nota: no exponemos la tasa en la respuesta pública; queda manejada en backend.


# -------- util --------
ALLOWED_METHODS_USD_ONLY = {"binance", "zinli"}  # estos se mantienen en USD

def require_admin(x_admin_key: str = Header(default="")):
    if not settings.admin_api_key or x_admin_key != settings.admin_api_key:
        raise HTTPException(401, "Admin key inválida")

def _validate_quantity(q: int):
    if q < 1 or q > 50:
        raise HTTPException(400, "Cantidad inválida (1–50)")

# -------- salud / config --------
@app.get("/health")
async def health():
    raffle = svc.get_current_raffle(raise_if_missing=False)
    return {"status": "ok", "active_raffle": bool(raffle)}

# Ahora acepta raffle_id opcional para devolver la config de esa rifa
@app.get("/config")
async def public_config(raffle_id: Optional[str] = Query(default=None)):
    # La lógica interna entrega datos públicos de la rifa.
    # El front puede usar /quote para ver montos totales según método.
    return svc.public_config(raffle_id=raffle_id)

# -------- rifas (nuevo) --------
@app.get("/raffles/list")
async def raffles_list():
    return {"raffles": svc.list_open_raffles()}

# -------- tasa (admin/público) --------
@app.get("/rate/current")
async def get_current_rate():
    """
    Devuelve si hay tasa activa y su 'source' (no obligatorio usarla en el front).
    No muestres la tasa al usuario si no quieres; este endpoint es útil para auditoría.
    """
    return svc.get_rate_info()

@app.post("/admin/rate/set")
async def set_rate(body: Dict[str, float], x_admin_key: str = Header(default="")):
    require_admin(x_admin_key)
    rate = float(body.get("rate"))
    return svc.set_rate(rate, source="manual")

@app.post("/admin/rate/update")
async def update_rate(x_admin_key: str = Header(default="")):
    require_admin(x_admin_key)
    # Obtiene de open.er-api.com u otra fuente configurada en logic.py
    rate = svc.fetch_external_rate()
    return svc.set_rate(rate, source="auto")

# -------- cotización de montos --------
@app.post("/quote", response_model=QuoteResponse)
async def quote_amount(req: QuoteRequest):
    """
    Calcula totales según cantidad, rifa y método.
    - Para métodos en USD-only (binance/zinli): deja USD y calcula VES internamente solo para mostrarse (opcional).
    - Para métodos locales (pago_movil/transferencia/etc.): calcula VES con tasa del día (sin exponer la tasa).
    """
    _validate_quantity(req.quantity)
    # Normalizar método
    method = (req.method or "pago_movil").strip().lower()

    # La lógica del cálculo vive en el servicio para mantener una sola fuente de verdad
    # Regresa: {raffle_id, method, unit_price_usd, total_usd, unit_price_ves?, total_ves?}
    try:
        return svc.quote_amount(
            quantity=req.quantity,
            raffle_id=req.raffle_id,
            method=method,
            usd_only=(method in ALLOWED_METHODS_USD_ONLY),
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# -------- tickets / pagos --------
@app.post("/tickets/reserve", response_model=ReserveResponse)
async def reserve(req: ReserveRequest):
    _validate_quantity(req.quantity)
    return {"tickets": svc.reserve_tickets(req.email, req.quantity, raffle_id=req.raffle_id)}

@app.post("/tickets/paid")
async def mark_paid(req: MarkPaidRequest):
    svc.mark_paid(req.ticket_ids, req.payment_ref)
    return {"ok": True}

# Endpoint unificado de pago; ahora pasa raffle_id y method al servicio
@app.post("/payments/submit")
async def submit_payment_unified(req: PaymentRequest):
    _validate_quantity(req.quantity)
    method = (req.method or "").strip().lower() or None
    try:
        data = svc.create_mobile_payment(
            req.email,
            req.quantity,
            req.reference,
            req.evidence_url,
            raffle_id=req.raffle_id,
            method=method,  # <- importante para respetar regla USD-only vs VES
        )
        return {"message": "Pago registrado. Verificación 24–72h.", **data}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/payments/verify")
async def verify_payment(req: VerifyAdminRequest, x_admin_key: str = Header(default="")):
    require_admin(x_admin_key)
    return svc.admin_verify_payment(req.payment_id, req.approve)

@app.post("/tickets/check")
async def check_status(req: CheckRequest):
    return svc.check_status(req.ticket_number, req.reference, req.email)

# -------- sorteo --------
@app.post("/draw/start", response_model=DrawStartResponse)
async def draw_start(req: DrawStartRequest):
    draw_id = svc.start_draw(req.seed)
    return {"draw_id": draw_id}

@app.post("/draw/pick")
async def draw_pick(req: DrawPickRequest):
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
async def index(request: Request):
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return {"message": "Sube tu frontend en /static (index.html)"}
