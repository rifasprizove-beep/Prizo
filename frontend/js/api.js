// api.js — helper con fallback y timeout

const ORIGIN = window.location.origin.replace(/\/$/, "");

// Lee PRIZO_API_BASE o API_BASE (compat)
const EXTERNAL_BASE =
  ((window.PRIZO_API_BASE ?? window.API_BASE) || "")
    .replace(/\/$/, "") || null;

if (!EXTERNAL_BASE) {
  console.warn("[PRIZO] API base no definida en config.js; usando ORIGIN como fallback.");
}

const DEFAULT_TIMEOUT_MS = 12000;

/**
 * Intenta extraer un mensaje de error útil del backend.
 */
async function readDetail(r) {
  try {
    const data = await r.clone().json();

    // FastAPI/Pydantic suele enviar detail como array [{loc, msg, type}, ...]
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
 * fetch con múltiples bases (EXTERNAL_BASE -> ORIGIN -> ORIGIN/api)
 * - Conserva método, headers y body del request original.
 * - Aplica timeout por request.
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

/* -------------------- RIFAS -------------------- */

export const listRaffles = async () =>
  (await (await apiFetch("/raffles/list")).json()).raffles || [];

// ✅ Evita enviar ?raffle_id=undefined
export const loadConfig = async (id) => {
  const q = (typeof id === "string" && id)
    ? `?raffle_id=${encodeURIComponent(id)}`
    : "";
  return await (await apiFetch(`/config${q}`)).json();
};

export const getProgress = async (id) =>
  (await (await apiFetch(`/raffles/progress?raffle_id=${encodeURIComponent(id)}`)).json()).progress || {};

/**
 * Cotiza total en VES para quantity de tickets.
 */
export const quoteTotal = async (id, q) =>
  await (
    await apiFetch("/quote", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ raffle_id: id, quantity: q, method: "pago_movil" }),
    })
  ).json();

/* -------------------- TICKETS -------------------- */

/**
 * Reserva tickets (ANÓNIMO).
 * Formas de uso:
 *  reserve(raffleId, 3)
 *  reserve(raffleId, { quantity: 3 })
 *  reserve(raffleId, { ticket_ids: ["...","..."] })
 *  reserve(raffleId, { ticket_numbers: [10, 11] })
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

  return await (
    await apiFetch("/tickets/reserve", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    })
  ).json();
};

/**
 * Libera tickets reservados.
 */
export const release = async (ids) =>
  apiFetch("/tickets/release", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ticket_ids: ids }),
  });

/* -------------------- PAGOS -------------------- */

/**
 * Envía pago:
 *  - Si has reservado (tienes ticket_ids) usa /payments/reserve_submit
 *    (Asegúrate de incluir hold_id en payload)
 *  - Si NO reservaste antes, usa /payments/submit
 * El payload puede incluir document_id, state y phone.
 */
export const submitPay = async (payload, hasIds) => {
  const path = hasIds ? "/payments/reserve_submit" : "/payments/submit";
  const r = await apiFetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return r.json();
};

/* -------------------- CONSULTAS -------------------- */

export const checkTicket = async (body) =>
  await (
    await apiFetch("/tickets/check", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    })
  ).json();

// versión para depuración / cache-busting
console.log("PRIZO_API_VERSION", "20251022b", { EXTERNAL_BASE, ORIGIN });
