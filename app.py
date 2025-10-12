import os
from typing import List, Optional, Any, Dict
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr  # Importo EmailStr para mejor validación

from logic import RaffleService, make_client, settings

app = FastAPI(title="Raffle Pro API", version="2.2.0")

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

# -------- modelos (manteniendo estructura; agrego raffle_id opcional donde aplica) --------
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

# -------- util --------
def require_admin(x_admin_key: str = Header(default="")):
    if not settings.admin_api_key or x_admin_key != settings.admin_api_key:
        raise HTTPException(401, "Admin key inválida")

# -------- salud / config --------
@app.get("/health")
async def health():
    raffle = svc.get_current_raffle(raise_if_missing=False)
    return {"status": "ok", "active_raffle": bool(raffle)}

# Ahora acepta raffle_id opcional para devolver la config de esa rifa
@app.get("/config")
async def public_config(raffle_id: Optional[str] = Query(default=None)):
    return svc.public_config(raffle_id=raffle_id)

# -------- rifas (nuevo) --------
@app.get("/raffles/list")
async def raffles_list():
    return {"raffles": svc.list_open_raffles()}

# -------- tasa (admin) --------
@app.post("/admin/rate/set")
async def set_rate(body: Dict[str, float], x_admin_key: str = Header(default="")):
    require_admin(x_admin_key)
    rate = float(body.get("rate"))
    return svc.set_rate(rate, source="manual")

@app.post("/admin/rate/update")
async def update_rate(x_admin_key: str = Header(default="")):
    require_admin(x_admin_key)
    rate = svc.fetch_external_rate()
    return svc.set_rate(rate, source="auto")

# -------- tickets / pagos --------
@app.post("/tickets/reserve", response_model=ReserveResponse)
async def reserve(req: ReserveRequest):
    if req.quantity < 1 or req.quantity > 50:
        raise HTTPException(400, "Cantidad inválida (1–50)")
    return {"tickets": svc.reserve_tickets(req.email, req.quantity, raffle_id=req.raffle_id)}

@app.post("/tickets/paid")
async def mark_paid(req: MarkPaidRequest):
    svc.mark_paid(req.ticket_ids, req.payment_ref)
    return {"ok": True}

# Endpoint unificado de pago; ahora pasa raffle_id al servicio
@app.post("/payments/submit")
async def submit_payment_unified(req: PaymentRequest):
    try:
        data = svc.create_mobile_payment(
            req.email, req.quantity, req.reference, req.evidence_url, raffle_id=req.raffle_id
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
