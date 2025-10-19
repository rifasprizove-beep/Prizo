from typing import Optional, Any, Dict, List
from pathlib import Path
import threading
import os

from fastapi import (
    FastAPI, Form, HTTPException, Request, Header, Query, File, UploadFile, Body
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend.api.schemas import (
    ReserveRequest, ReserveResponse, MarkPaidRequest,
    DrawStartRequest, DrawStartResponse, DrawPickRequest,
    VerifyAdminRequest, CheckRequest,
    QuoteRequest, QuoteResponse, SubmitReservedRequest
)
from backend.core.settings import settings, make_client
from backend.services.raffle_service import RaffleService
from backend.services.cloudinary_uploader import upload_file, is_configured
from backend.services.utils import cents_to_usd, round2


app = FastAPI(title="Raffle Pro API", version="3.1.0")

# ---------------- CORS ----------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------- Static (dos ubicaciones posibles) ----------------
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

# ---------------- SHIM /api/* (compat front antiguo) ----------
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

@app.get("/healthz")
def healthz():
    return health()

@app.get("/config")
def public_config(raffle_id: Optional[str] = Query(default=None)):
    """Config pública. Nunca rompe el front: siempre devuelve valores por defecto sanos."""
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
    """Limpia reservas vencidas (defensa adicional)."""
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
            .update({'reserved_until': None, 'email': None, 'reserved_by': None}) \
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
def reserve_tickets(req: ReserveRequest):
    """
    Reserva anónima. Devuelve hold_id y listado de tickets.
    """
    try:
        qty = int(req.quantity)
        if qty < 1 or qty > 50:
            raise HTTPException(422, "quantity debe estar entre 1 y 50")

        res = svc.reserve_tickets(qty=qty, raffle_id=req.raffle_id)
        return {"hold_id": res["hold_id"], "tickets": res["tickets"]}

    except HTTPException:
        raise
    except ValueError as ve:
        raise HTTPException(422, str(ve))
    except RuntimeError as re:
        raise HTTPException(409, str(re))
    except Exception as e:
        raise HTTPException(500, f"Fallo al reservar: {e}")


@app.post("/tickets/release")
def release_tickets(payload: Dict[str, Any]):
    try:
        ids = payload.get("ticket_ids") or []
        if not isinstance(ids, list) or not all(isinstance(x, str) for x in ids):
            raise HTTPException(422, "ticket_ids debe ser lista de strings")
        if not ids:
            return {"ok": True}
        svc.client.table("tickets").update(
            {"reserved_until": None, "email": None, "reserved_by": None}
        ).in_("id", ids).eq("verified", False).execute()
        return {"ok": True}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(500, f"No se pudieron liberar: {e}")


@app.post("/tickets/paid")
def mark_paid(req: MarkPaidRequest):
    svc.mark_paid(req.ticket_ids, req.payment_ref)
    return {"ok": True}


@app.post("/payments/submit")
async def submit_payment_unified(
    request: Request,
    file: Optional[UploadFile] = File(None),
    # Campos cuando viene multipart/form-data
    email: Optional[str] = Form(None),
    reference: Optional[str] = Form(None),
    method: Optional[str] = Form(None),
    raffle_id: Optional[str] = Form(None),
    quantity: Optional[int] = Form(None),
    evidence_url: Optional[str] = Form(None),
    document_id: Optional[str] = Form(None),  # <-- Cédula / RIF
    state: Optional[str] = Form(None),        # <-- Estado / región
    phone: Optional[str] = Form(None),        # <-- Teléfono
):
    """
    Acepta:
    - multipart/form-data con campos de formulario y archivo 'file',
    - o JSON (PaymentRequest).
    Exige email, reference, document_id, state y phone (si llega por multipart).
    Sube 'file' a Cloudinary si no llega 'evidence_url'.
    """
    try:
        ctype = (request.headers.get("content-type") or "").lower()
        if "multipart/form-data" in ctype:
            # --------- Flujo multipart ---------
            if not email:
                raise HTTPException(400, "email requerido")
            if not reference:
                raise HTTPException(400, "reference requerida")
            if not document_id:
                raise HTTPException(400, "document_id (cédula/RIF) es requerido")
            if not state:
                raise HTTPException(400, "state (estado) es requerido")
            if not phone:
                raise HTTPException(400, "phone (teléfono) es requerido")
            if not quantity or int(quantity) < 1:
                raise HTTPException(400, "quantity requerido (>= 1)")

            # Subir la imagen si viene adjunta y no hay evidence_url explícita
            if file and not evidence_url:
                if not is_configured():
                    raise HTTPException(500, "Cloudinary no configurado en el servidor")
                evidence_url = await upload_file(file, folder="prizo_evidences")

            data = svc.create_mobile_payment(
                email=email,
                quantity=int(quantity),
                reference=reference,
                evidence_url=evidence_url,
                raffle_id=raffle_id,
                method=(method or "pago_movil").lower(),
                document_id=document_id,
                state=state,
                phone=phone,
            )
            return {"message": "Pago registrado. Verificación 24–72h.", **data}

        # --------- Flujo JSON (compat) ---------
        body = await request.json()
        from backend.api.schemas import PaymentRequest as _PR
        req = _PR(**body)

        if not req.quantity or req.quantity < 1:
            raise HTTPException(400, "Cantidad inválida (debe ser >= 1)")
        if not req.reference:
            raise HTTPException(400, "reference requerida")
        if not req.document_id:
            raise HTTPException(400, "document_id (cédula/RIF) es requerido")
        if not req.state:
            raise HTTPException(400, "state (estado) es requerido")

        data = svc.create_mobile_payment(
            req.email,
            req.quantity,
            req.reference,
            req.evidence_url,
            raffle_id=req.raffle_id,
            method=(req.method or "pago_movil").lower(),
            document_id=req.document_id,
            state=req.state,
            phone=getattr(req, "phone", None),
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
    """
    Front ya reservó ticket_ids (anónimo) y tiene hold_id; valida y crea el pago PENDIENTE.
    También guarda document_id, state y phone (si llegan) y congela amount_ves + rate_used.
    """
    try:
        if not req.ticket_ids:
            raise HTTPException(400, "ticket_ids requerido")
        if not req.reference:
            raise HTTPException(400, "reference requerida")
        if not req.document_id:
            raise HTTPException(400, "document_id (cédula/RIF) es requerido")
        if not req.state:
            raise HTTPException(400, "state (estado) es requerido")
        if not req.hold_id:
            raise HTTPException(400, "hold_id requerido para confirmar los tickets")

        tq = svc.client.table("tickets") \
            .select("id, raffle_id, verified, reserved_until, reserved_by, email") \
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
            if not t.get("reserved_until") or t["reserved_until"] < now_iso:
                raise HTTPException(400, "La reserva de algún ticket expiró")
            if (t.get("reserved_by") or "") != req.hold_id:
                raise HTTPException(400, "Algún ticket no pertenece a este hold_id")

        # Reclama: asigna email a los tickets y libera reserved_by
        try:
            (
                svc.client.table("tickets")
                .update({"email": (req.email or "").strip().lower(), "reserved_by": None})
                .in_("id", req.ticket_ids)
                .execute()
            )
        except Exception:
            pass

        # ---- Calcular monto en Bs y tasa "congelados"
        qty = len(req.ticket_ids)
        raffle_id_final = req.raffle_id or tickets[0]["raffle_id"]
        raffle_row = svc.get_raffle_by_id(raffle_id_final)
        unit_price_usd = cents_to_usd(raffle_row["ticket_price_cents"]) if raffle_row else 0.0
        total_usd = round2(unit_price_usd * qty)
        rate_used = svc.get_rate()
        amount_ves = round2(total_usd * rate_used)

        pay = {
            "raffle_id": raffle_id_final,
            "email": (req.email or "").strip().lower(),
            "quantity": qty,
            "reference": req.reference,
            "evidence_url": req.evidence_url,
            "status": "pending",
            "method": (req.method or "pago_movil"),
            "document_id": req.document_id,
            "state": req.state,
            "phone": getattr(req, "phone", None),
            # nuevos campos
            "amount_ves": amount_ves,
            "rate_used": rate_used,
        }
        presp = svc.client.table("payments").insert(pay).execute()
        if not presp.data:
            raise RuntimeError("No se pudo crear el pago")
        payment_id = presp.data[0]["id"]

        links = [{"payment_id": payment_id, "ticket_id": tid} for tid in req.ticket_ids]
        svc.client.table("payment_tickets").insert(links).execute()

        # opcional: refrescar ventana mientras verifica admin
        try:
            from datetime import timedelta
            new_until = (svc._now_utc() + timedelta(minutes=10)).isoformat().replace("+00:00", "Z")
            svc.client.table("tickets").update({"reserved_until": new_until}).in_("id", req.ticket_ids).execute()
        except Exception:
            pass

        return {"payment_id": payment_id, "status": "pending", "amount_ves": amount_ves, "rate_used": rate_used}
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
                .update({'reserved_until': None, 'email': None, 'reserved_by': None}) \
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


# --------- Ejecutable local (y compatible con Render si usas `python app.py`) ---------
if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", "8000"))
    uvicorn.run("backend.api.app:app", host="0.0.0.0", port=port, proxy_headers=True)
