from typing import Optional, Any, Dict, List
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Header, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from backend.api.schemas import (
    ReserveRequest, ReserveResponse, MarkPaidRequest,
    DrawStartRequest, DrawStartResponse, DrawPickRequest,
    PaymentRequest, VerifyAdminRequest, CheckRequest,
    QuoteRequest, QuoteResponse, SubmitReservedRequest
)
from backend.core.settings import settings, make_client
from backend.services.raffle_service import RaffleService

app = FastAPI(title="Raffle Pro API", version="2.7.0")

# ---------------- CORS ----------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------- Static ----------------
BASE_DIR = Path(__file__).resolve().parent.parent  # carpeta raíz (una arriba de backend/)
STATIC_DIR = BASE_DIR / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
else:
    print("[WARN] 'static/' no existe; se salta el montaje.")

# ---------------- Servicios ----------------
client = make_client()
svc = RaffleService(client)

USD_ONLY = {"binance", "zinli", "zelle"}


def require_admin(x_admin_key: str = Header(default="")):
    if not settings.admin_api_key or x_admin_key != settings.admin_api_key:
        raise HTTPException(401, "Admin key inválida")


def _validate_quantity(q: int):
    if q < 1 or q > 50:
        raise HTTPException(400, "Cantidad inválida (1–50)")


# -------- Ejemplo mínimo de pago móvil (fallback para /config) --------
SAMPLE_PAYMENT_METHODS: Dict[str, Dict[str, str]] = {
    "pago_movil": {
        "Banco": "Banesco",
        "Teléfono": "0414-1234567",
        "Cédula/RIF": "V-12.345.678",
        "Titular": "PRIZO",
        "Tipo": "Pago Móvil",
    }
}

# ---------------- SHIM /api/* ----------
@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def api_prefix_passthrough(path: str, request: Request):
    return RedirectResponse(url=f"/{path}", status_code=307)

# ---------------- Salud / Config ----------------
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
    si ocurre algo, devuelve valores seguros y ejemplo de pago móvil.
    """
    try:
        cfg = svc.public_config(raffle_id=raffle_id) or {}
    except Exception as e:
        cfg = {"error": f"/config fallback: {str(e)}"}

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
        "payment_methods": SAMPLE_PAYMENT_METHODS,  # fallback
        "progress": {},
    }

    # Respetar valores reales del backend
    if isinstance(cfg.get("payment_methods"), dict) and cfg["payment_methods"]:
        base["payment_methods"] = cfg["payment_methods"]
    if "progress" in cfg and isinstance(cfg["progress"], dict):
        base["progress"] = cfg["progress"]

    base.update(cfg)
    return base

# ---------------- Rifas ----------------
@app.get("/raffles/list")
def raffles_list():
    try:
        return {"raffles": svc.list_open_raffles()}
    except Exception as e:
        return {"raffles": [], "error": str(e)}


@app.get("/raffles/progress")
def raffle_progress(raffle_id: Optional[str] = Query(default=None)):
    """
    Endpoint para consultar el progreso de una rifa.
    Si no se pasa raffle_id, usa la rifa activa.
    """
    raffle = svc.get_raffle_by_id(raffle_id) or svc.get_current_raffle()
    if not raffle:
        raise HTTPException(404, "No hay rifa activa")
    return {"raffle_id": raffle["id"], "progress": svc.progress_for_public(raffle)}

# ---------------- Tasa ----------------
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

# ---------------- Cotización (soft-fail) ----------------
@app.post("/quote", response_model=QuoteResponse)
def quote_amount(req: QuoteRequest):
    q = int(req.quantity or 0)
    if q < 1:
        return QuoteResponse(
            raffle_id=None, method=(req.method or "pago_movil"),
            unit_price_usd=None, total_usd=None,
            unit_price_ves=None, total_ves=None,
            error="Cantidad inválida (debe ser >= 1)",
        )

    method = (req.method or "pago_movil").strip().lower()
    try:
        data = svc.quote_amount(
            quantity=q,
            raffle_id=req.raffle_id,
            method=method,
            usd_only=(method in USD_ONLY),
        )
        return QuoteResponse(**data, error=None)
    except Exception as e:
        return QuoteResponse(
            raffle_id=None, method=method,
            unit_price_usd=None, total_usd=None,
            unit_price_ves=None, total_ves=None,
            error=str(e),
        )

# ---------------- Tickets / Pagos ----------------
@app.post("/tickets/reserve", response_model=ReserveResponse)
def reserve(req: ReserveRequest):
    """
    Modos:
    - req.ticket_ids -> bloquear IDs existentes.
    - req.ticket_numbers -> crear/bloquear números específicos si no existen.
    - si nada de lo anterior -> crear 'quantity' tickets nuevos.
    """
    ticket_ids = getattr(req, "ticket_ids", None) or None
    ticket_numbers = getattr(req, "ticket_numbers", None) or None

    if ticket_ids:
        tickets = svc.reserve_tickets(
            email=req.email,
            qty=0,
            raffle_id=req.raffle_id,
            ticket_ids=ticket_ids,
        )
        return {"tickets": tickets}

    if ticket_numbers:
        tickets = svc.reserve_tickets(
            email=req.email,
            qty=0,
            raffle_id=req.raffle_id,
            ticket_numbers=ticket_numbers,
        )
        return {"tickets": tickets}

    _validate_quantity(req.quantity)
    return {"tickets": svc.reserve_tickets(req.email, req.quantity, raffle_id=req.raffle_id)}


@app.post("/tickets/release")
def release_tickets(body: Dict[str, Any]):
    """
    Libera reservas (no borra tickets).
    """
    ids = body.get("ticket_ids") or []
    if not ids:
        raise HTTPException(400, "ticket_ids required")

    svc.client.table("tickets") \
        .update({"reserved_until": None, "email": None}) \
        .in_("id", ids) \
        .eq("verified", False) \
        .execute()
    return {"released": len(ids)}


@app.post("/tickets/paid")
def mark_paid(req: MarkPaidRequest):
    svc.mark_paid(req.ticket_ids, req.payment_ref)
    return {"ok": True}


@app.post("/payments/submit")
def submit_payment_unified(req: PaymentRequest):
    """
    Flujo 'clásico': creamos el pago e inmediatamente reservamos N tickets nuevos.
    """
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


@app.post("/payments/reserve_submit")
def submit_reserved_payment(req: SubmitReservedRequest):
    """
    Flujo 'selección por número': el front ya tiene ticket_ids reservados.
    Validamos que siguen bloqueados/no vencidos, y creamos el pago.
    """
    try:
        if not req.ticket_ids:
            raise HTTPException(400, "ticket_ids requerido")

        tq = svc.client.table("tickets") \
            .select("id, raffle_id, verified, reserved_until, email") \
            .in_("id", req.ticket_ids) \
            .execute()
        tickets = tq.data or []
        if len(tickets) != len(req.ticket_ids):
            raise HTTPException(400, "Algunos tickets no existen")

        now_iso = svc._now_iso()
        for t in tickets:
            if t.get("verified"):
                raise HTTPException(400, "Algún ticket ya fue pagado")
            if t.get("raffle_id") and req.raffle_id and t["raffle_id"] != req.raffle_id:
                raise HTTPException(400, "Ticket no pertenece a la rifa indicada")
            if not t.get("reserved_until"):
                raise HTTPException(400, "Algún ticket no está reservado")
            if t["reserved_until"] < now_iso:
                raise HTTPException(400, "La reserva de algún ticket expiró")
            if t.get("email") and t["email"] != req.email:
                raise HTTPException(400, "Algún ticket está reservado por otro email")

        pay = {
            "raffle_id": req.raffle_id or tickets[0]["raffle_id"],
            "email": req.email,
            "quantity": len(req.ticket_ids),
            "reference": req.reference,
            "evidence_url": req.evidence_url,
            "status": "pending",
            "method": (req.method or "pago_movil"),
        }
        presp = svc.client.table("payments").insert(pay).select("id").execute()
        if not presp.data:
            raise RuntimeError("No se pudo crear el pago")
        payment_id = presp.data[0]["id"]

        links = [{"payment_id": payment_id, "ticket_id": tid} for tid in req.ticket_ids]
        svc.client.table("payment_tickets").insert(links).execute()

        return {"payment_id": payment_id, "status": "pending"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post("/payments/verify")
def verify_payment(req: VerifyAdminRequest, x_admin_key: str = Header(default="")):
    require_admin(x_admin_key)
    return svc.admin_verify_payment(req.payment_id, req.approve)


@app.post("/tickets/check")
def check_status(req: CheckRequest):
    return svc.check_status(req.ticket_number, req.reference, req.email)

# ---------------- Sorteo ----------------
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

# ---------------- Front ----------------
@app.get("/")
def index(request: Request):
    index_path = STATIC_DIR / "index.html"
    if index_path.exists():
        return FileResponse(str(index_path))
    return {"message": "Sube tu frontend en /static (index.html)"}
