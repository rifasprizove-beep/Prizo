from typing import Optional, Any, Dict, List
from pathlib import Path
import threading

from fastapi import FastAPI, HTTPException, Request, Header, Query, File, UploadFile, Body
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
from backend.services.cloudinary_uploader import upload_file, is_configured


app = FastAPI(title="Raffle Pro API", version="2.7.0")

# ---------------- CORS ----------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------- Static (intenta dos ubicaciones) ----------------
# Estructura esperada del proyecto:
# <root>/
#   backend/app.py   (este archivo)
#   static/          (index.html, style.css, js/...)   <- preferida
#   └─ o backend/static/                                <- alternativa
BASE_DIR = Path(__file__).resolve().parent.parent     # <root>/
STATIC_ROOT_1 = BASE_DIR / "static"
STATIC_ROOT_2 = BASE_DIR / "backend" / "static"

mounted = False
for folder in (STATIC_ROOT_1, STATIC_ROOT_2):
    if folder.exists():
        app.mount("/static", StaticFiles(directory=str(folder)), name="static")
        print(f"[STATIC] sirviendo /static desde: {folder}")
        mounted = True
        break

if not mounted:
    print("[WARN] No encontré carpeta 'static' ni en raíz ni en backend/.")

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


# -------- Fallback mínimo de Pago Móvil para /config --------
SAMPLE_PAYMENT_METHODS: Dict[str, Dict[str, str]] = {
    "pago_movil": {
        "Banco": "Banesco",
        "Teléfono": "0414-1234567",
        "Cédula/RIF": "V-12.345.678",
        "Titular": "PRIZO",
        "Tipo": "Pago Móvil",
    }
}

# ---------------- SHIM /api/* (compat con front antiguo) ----------
@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
async def api_prefix_passthrough(path: str, request: Request):
    # Redirección 307 preserva método y cuerpo. Útil para compatibilidad con front viejo.
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
    """Config pública. Nunca rompe el front: siempre devuelve valores saneados."""
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
    """Progreso de una rifa (si no pasas id, usa la activa)."""
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


@app.post('/admin/cleanup_reservations')
def admin_cleanup_reservations(x_admin_key: str = Header(default="")):
    """Limpia reservas vencidas."""
    require_admin(x_admin_key)
    try:
        raffles = svc.list_open_raffles() or []
        for r in raffles:
            try:
                svc._clear_expired_reservations(r.get('id'))
            except Exception:
                pass

        now_iso = svc._now_iso()
        svc.client.table('tickets') \
            .update({'reserved_until': None, 'email': None}) \
            .lt('reserved_until', now_iso) \
            .eq('verified', False) \
            .execute()

        return {'ok': True, 'message': 'Cleanup attempted'}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


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
    - ticket_ids -> bloquear IDs existentes.
    - ticket_numbers -> crear/bloquear números específicos si no existen.
    - si nada de lo anterior -> crear 'quantity' tickets nuevos (aleatorios).
    """
    ticket_ids = getattr(req, "ticket_ids", None) or None
    ticket_numbers = getattr(req, "ticket_numbers", None) or None

    if ticket_ids:
        tickets = svc.reserve_tickets(
            email=req.email, qty=0, raffle_id=req.raffle_id, ticket_ids=ticket_ids,
        )
        return {"tickets": tickets}

    if ticket_numbers:
        tickets = svc.reserve_tickets(
            email=req.email, qty=0, raffle_id=req.raffle_id, ticket_numbers=ticket_numbers,
        )
        return {"tickets": tickets}

    _validate_quantity(req.quantity)
    return {"tickets": svc.reserve_tickets(req.email, req.quantity, raffle_id=req.raffle_id)}


@app.post("/tickets/release")
def release_tickets(body: Dict[str, Any]):
    """Libera reservas (no borra tickets)."""
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
async def submit_payment_unified(request: Request,
                                 file: Optional[UploadFile] = File(None),
                                 email: Optional[str] = Form(None),
                                 reference: Optional[str] = Form(None),
                                 method: Optional[str] = Form(None),
                                 raffle_id: Optional[str] = Form(None),
                                 quantity: Optional[int] = Form(None),
                                 evidence_url: Optional[str] = Form(None)):
    """
    Acepta:
    - JSON (PaymentRequest) como antes, o
    - multipart/form-data con campos de formulario y un archivo 'file'.
    Si llega 'file', se sube a Cloudinary y se usa su secure_url.
    """
    try:
        ctype = request.headers.get("content-type", "")
        if "multipart/form-data" in ctype:
            # multipart: tomar campos del formulario (ya los mapeamos con Form)
            if not email:
                raise HTTPException(400, "email requerido")
            if not quantity or quantity < 1:
                raise HTTPException(400, "quantity requerido (>=1)")

            # Subir la imagen si viene adjunta y no hay evidence_url
            if file and not evidence_url:
                if not is_configured():
                    raise HTTPException(500, "Cloudinary no configurado")
                evidence_url = await upload_file(file, folder="prizo_evidences")

            data = svc.create_mobile_payment(
                email=email,
                quantity=int(quantity),
                reference=reference,
                evidence_url=evidence_url,
                raffle_id=raffle_id,
                method=(method or "pago_movil").lower()
            )
            return {"message": "Pago registrado. Verificación 24–72h.", **data}

        # JSON (flujo original)
        body = await request.json()
        from backend.api.schemas import PaymentRequest as _PR
        req = _PR(**body)

        if not req.quantity or req.quantity < 1:
            raise HTTPException(400, "Cantidad inválida (debe ser >= 1)")

        data = svc.create_mobile_payment(
            req.email, req.quantity, req.reference, req.evidence_url,
            raffle_id=req.raffle_id, method=(req.method or "pago_movil").lower(),
        )
        return {"message": "Pago registrado. Verificación 24–72h.", **data}

    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@app.post('/payments/upload_evidence')
async def payments_upload_evidence(file: UploadFile = File(...)):
    """Sube a Cloudinary y devuelve { secure_url }."""
    if not is_configured():
        raise HTTPException(status_code=500, detail="Cloudinary not configured on server")
    try:
        url = await upload_file(file, folder='prizo_evidences')
        return {"secure_url": url}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/payments/reserve_submit")
def submit_reserved_payment(req: SubmitReservedRequest):
    """Front ya reservó ticket_ids; valida y crea el pago."""
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
# Redirige SIEMPRE al index del folder estático (evita el mensaje en Render)
@app.get("/")
def root_redirect():
    return RedirectResponse(url="/static/index.html", status_code=307)


# ---------------- Background cleanup task ----------------
_cleanup_thread = None
_cleanup_stop = threading.Event()


def _cleanup_loop(interval_seconds: int):
    while not _cleanup_stop.wait(interval_seconds):
        try:
            raffles = svc.list_open_raffles() or []
            for r in raffles:
                try:
                    svc._clear_expired_reservations(r.get('id'))
                except Exception:
                    pass

            now_iso = svc._now_iso()
            svc.client.table('tickets') \
                .update({'reserved_until': None, 'email': None}) \
                .lt('reserved_until', now_iso) \
                .eq('verified', False) \
                .execute()
        except Exception:
            # mantener el loop vivo
            pass


@app.on_event('startup')
def start_background_cleanup():
    global _cleanup_thread, _cleanup_stop
    _cleanup_stop.clear()
    interval = int(getattr(settings, 'cleanup_interval_seconds', 60) or 60)
    _cleanup_thread = threading.Thread(target=_cleanup_loop, args=(interval,), daemon=True)
    _cleanup_thread.start()


@app.on_event('shutdown')
def stop_background_cleanup():
    global _cleanup_thread, _cleanup_stop
    _cleanup_stop.set()
    if _cleanup_thread:
        _cleanup_thread.join(timeout=2)
