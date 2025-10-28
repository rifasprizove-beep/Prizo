// api.js — helper con fallback y timeout (versión robusta)

// ====== BASES ======
const ORIGIN = window.location.origin.replace(/\/$/, "");

// Lee PRIZO_API_BASE o API_BASE (compat)
const EXTERNAL_BASE =
  ((window.PRIZO_API_BASE ?? window.API_BASE) || "")
    .replace(/\/$/, "") || null;

if (!EXTERNAL_BASE) {
  console.warn("[PRIZO] API base no definida en config.js; usando ORIGIN como fallback.");
}

const DEFAULT_TIMEOUT_MS = 12000;

// ====== UTILES ======

/**
 * Intenta extraer un mensaje de error útil del backend.
 * - Soporta FastAPI detail como string o como array de errores de validación.
 */
async function readDetail(r) {
  try {
    const data = await r.clone().json();

    // Pydantic/fastapi validation: array de objetos {loc, msg, type}
    if (Array.isArray(data?.detail)) {
      const msg = data.detail
        .map(d => {
          const loc = Array.isArray(d?.loc) ? d.loc.join(".") : (d?.loc ?? "");
          return `${loc ? loc + ": " : ""}${d?.msg ?? ""}`.trim();
        })
        .filter(Boolean)
        .join(" | ");
      if (msg) return msg;
    }

    return data?.detail || data?.error || data?.message || null;
  } catch {
    try {
      const txt = await r.text();
      return txt && txt.length < 400 ? txt : null;
    } catch {
      return null;
    }
  }
}

/**
 * Devuelve JSON si la respuesta es application/json.
 * Si no, intenta parsear texto a JSON; si falla, retorna { error: ... }.
 */
async function safeJson(resp) {
  const ct = resp.headers.get("content-type") || "";
  if (ct.includes("application/json")) {
    try { return await resp.json(); }
    catch { /* cae al plan B */ }
  }
  const text = await resp.text();
  try { return JSON.parse(text); }
  catch { return { error: text || resp.statusText || "Respuesta vacía" }; }
}

/**
 * fetch con múltiples bases (EXTERNAL_BASE -> ORIGIN -> ORIGIN/api)
 * - Conserva método, headers y body.
 * - Aplica timeout por request.
 * - Para respuestas !ok, intenta leer mensaje útil y lanza Error con detalle.
 */
export async function apiFetch(path, opts = {}) {
  const p = path.startsWith("/") ? path : `/${path}`;
  const urls = [
    EXTERNAL_BASE && EXTERNAL_BASE + p,
    ORIGIN + p,
    ORIGIN + "/api" + p,
  ].filter(Boolean);

  const timeout = typeof opts.timeout === "number" ? opts.timeout : DEFAULT_TIMEOUT_MS;

  let last;
  for (const url of urls) {
    const controller = new AbortController();
    const tid = setTimeout(() => controller.abort(new Error("timeout")), timeout);

    try {
      const r = await fetch(url, { ...opts, signal: controller.signal });
      clearTimeout(tid);

      if (r.ok) return r;

      const detail = await readDetail(r);
      last = new Error(`${detail ? detail + " — " : ""}HTTP ${r.status} @ ${url}`);
    } catch (e) {
      clearTimeout(tid);
      last = e?.name === "AbortError" ? new Error(`Timeout (${timeout}ms) @ ${url}`) : e;
    }
  }
  throw last || new Error("No se pudo contactar API");
}

/**
 * Igual a apiFetch pero devolviendo el cuerpo como objeto JSON de forma segura.
 * Si la respuesta no es JSON válido, devuelve { error: "..."} en lugar de romper.
 * OJO: si el status no es ok, apiFetch lanzará antes de llegar aquí.
 */
export async function apiJson(path, opts = {}) {
  const r = await apiFetch(path, opts);
  return await safeJson(r);
}

// ====== ENDPOINTS ======

/* -------------------- RIFAS -------------------- */

/** Lista pública de rifas */
export const listRaffles = async () => {
  const data = await apiJson("/raffles/list");
  return data?.raffles || [];
};

/** Carga config de una rifa (evita mandar ?raffle_id=undefined) */
export const loadConfig = async (id) => {
  const q = (typeof id === "string" && id)
    ? `?raffle_id=${encodeURIComponent(id)}`
    : "";
  return await apiJson(`/config${q}`);
};

/** Progreso (vendidos/disponibles) */
export const getProgress = async (id) => {
  const data = await apiJson(`/raffles/progress?raffle_id=${encodeURIComponent(id)}`);
  return data?.progress || {};
};

/** Cotiza total en VES para quantity de tickets (método por defecto: pago_movil) */
export const quoteTotal = async (id, q) => {
  return await apiJson("/quote", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ raffle_id: id, quantity: q, method: "pago_movil" }),
  });
};

/* -------------------- TICKETS -------------------- */

/**
 * Reserva tickets (ANÓNIMO).
 * Formas de uso:
 *   reserve(raffleId, 3)
 *   reserve(raffleId, { quantity: 3 })
 *   reserve(raffleId, { ticket_ids: ["...","..."] })
 *   reserve(raffleId, { ticket_numbers: [10, 11] })
 *
 * Respuesta: { hold_id, tickets: [...] }
 */
export const reserve = async (id, quantityOrOptions) => {
  const payload = { raffle_id: id };

  if (typeof quantityOrOptions === "number") {
    payload.quantity = Math.max(1, quantityOrOptions | 0);
  } else if (quantityOrOptions && typeof quantityOrOptions === "object") {
    const { quantity, ticket_ids, ticket_numbers } = quantityOrOptions;
    if (typeof quantity === "number") payload.quantity = Math.max(1, quantity | 0);
    if (Array.isArray(ticket_ids)) payload.ticket_ids = ticket_ids;
    if (Array.isArray(ticket_numbers)) payload.ticket_numbers = ticket_numbers;
  } else {
    payload.quantity = 1;
  }

  return await apiJson("/tickets/reserve", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
};

/** Libera tickets reservados */
export const release = async (ids) => {
  // No necesitamos la respuesta, pero parseamos por si backend retorna {ok:true}
  return await apiJson("/tickets/release", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ticket_ids: ids }),
  });
};

/* -------------------- PAGOS -------------------- */

/**
 * Envía pago:
 *  - Si reservaste (tienes ticket_ids) usa /payments/reserve_submit (incluye hold_id)
 *  - Si NO reservaste antes, usa /payments/submit
 * El payload puede incluir document_id, state y phone.
 */
export const submitPay = async (payload, hasIds) => {
  const path = hasIds ? "/payments/reserve_submit" : "/payments/submit";
  return await apiJson(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
};

/* -------------------- CONSULTAS -------------------- */

/** Verifica ticket(s) por referencia/email */
export const checkTicket = async (body) => {
  return await apiJson("/tickets/check", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
};

// versión para depuración / cache-busting
console.log("PRIZO_API_VERSION", "20251028c", { EXTERNAL_BASE, ORIGIN });
