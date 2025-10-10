# app.py
import os
from typing import List, Optional, Any, Dict
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from logic import RaffleService, make_client

app = FastAPI(title="Raffle Pro API", version="1.3.2")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # en prod, limita a tu dominio
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Static seguro ---
BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
else:
    print("[WARN] 'static/' no existe; se salta el montaje.")

# --- Supabase service ---
client = make_client()
RAFFLE_ID = os.getenv("RAFFLE_ID", "")
if not RAFFLE_ID:
    raise RuntimeError("RAFFLE_ID no está definido.")
svc = RaffleService(client, RAFFLE_ID)

# -------- MODELOS --------
class ReserveRequest(BaseModel):
    email: str
    quantity: int = 1

class ReserveResponse(BaseModel):
    tickets: List[Dict[str, Any]]  # [{id, number}]

class MarkPaidRequest(BaseModel):
    ticket_ids: List[str]
    payment_ref: str

class DrawStartRequest(BaseModel):
    seed: Optional[int] = None

class DrawStartResponse(BaseModel):
    draw_id: str

class DrawPickRequest(BaseModel):
    draw_id: str
    n: int = 1
    unique: bool = True

# -------- ENDPOINTS --------
@app.get("/health")
async def health():
    return {"status": "ok"}

@app.post("/tickets/reserve", response_model=ReserveResponse)
async def reserve(req: ReserveRequest):
    if req.quantity < 1 or req.quantity > 50:
        raise HTTPException(400, "Cantidad inválida (1–50)")
    try:
        tickets = svc.reserve_tickets(req.email, req.quantity)
        return {"tickets": tickets}
    except Exception as e:
        raise HTTPException(400, str(e))

@app.post("/tickets/paid")
async def mark_paid(req: MarkPaidRequest):
    try:
        svc.mark_paid(req.ticket_ids, req.payment_ref)
        return {"ok": True}
    except Exception as e:
        raise HTTPException(400, str(e))

@app.post("/draw/start", response_model=DrawStartResponse)
async def draw_start(req: DrawStartRequest):
    try:
        draw_id = svc.start_draw(req.seed)
        return {"draw_id": draw_id}
    except Exception as e:
        raise HTTPException(400, str(e))

@app.post("/draw/pick")
async def draw_pick(req: DrawPickRequest):
    if req.n < 1:
        raise HTTPException(400, "n debe ser >= 1")
    try:
        winners = svc.pick_winners(req.draw_id, req.n, req.unique)
        return {"winners": winners}
    except Exception as e:
        raise HTTPException(400, str(e))

@app.get("/")
async def index(request: Request):
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return {"message": "Sube tu frontend en /static (index.html)"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app:app",
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8000")),
        reload=False,
    )
