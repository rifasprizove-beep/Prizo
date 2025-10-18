// API helper con fallback
const ORIGIN = window.location.origin.replace(/\/$/, "");
const EXTERNAL_BASE = (window.PRIZO_API_BASE || "").replace(/\/$/, "") || null;

/**
 * Intenta extraer un mensaje de error útil del backend.
 */
async function readDetail(r) {
  try {
    const data = await r.clone().json();
    return data?.detail || data?.error || null;
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
 * fetch con múltiples bases: EXTERNAL_BASE -> ORIGIN -> ORIGIN/api
 * Conserva método, headers y body del request original.
 */
export async function apiFetch(path, opts = {}) {
  const p = path.startsWith("/") ? path : `/${path}`;
  const urls = [
    EXTERNAL_BASE && EXTERNAL_BASE + p,
    ORIGIN + p,
    ORIGIN + "/api" + p,
  ].filter(Boolean);

  let last;
  for (const url of urls) {
    try {
      const r = await fetch(url, opts);
      if (r.ok) return r;
      const detail = await readDetail(r);
      last = new Error(`${detail ? detail + " — " : ""}HTTP ${r.status} @ ${url}`);
    } catch (e) {
      last = e;
    }
  }
  throw last || new Error("No se pudo contactar API");
}

/* -------------------- RIFAS -------------------- */

export const listRaffles = async () =>
  (await (await apiFetch("/raffles/list")).json()).raffles || [];

export const loadConfig = async (id) =>
  await (await apiFetch(`/config?raffle_id=${encodeURIComponent(id)}`)).json();

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
 * Reserva tickets.
 * Uso compatible:
 *  reserve(raffleId, email, 3)
 *  reserve(raffleId, email, { quantity: 3 })
 *  reserve(raffleId, email, { ticket_ids: ["...","..."] })
 *  reserve(raffleId, email, { ticket_numbers: [10, 11] })
 */
export const reserve = async (id, email, quantityOrOptions) => {
  let payload = { raffle_id: id, email };

  if (typeof quantityOrOptions === "number") {
    payload.quantity = Math.max(1, quantityOrOptions | 0);
  } else if (quantityOrOptions && typeof quantityOrOptions === "object") {
    const { quantity, ticket_ids, ticket_numbers } = quantityOrOptions;
    if (typeof quantity === "number") payload.quantity = Math.max(1, quantity | 0);
    if (Array.isArray(ticket_ids)) payload.ticket_ids = ticket_ids;
    if (Array.isArray(ticket_numbers)) payload.ticket_numbers = ticket_numbers;
  } else {
    // Back-compat: si no pasan nada, reserva 1
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
