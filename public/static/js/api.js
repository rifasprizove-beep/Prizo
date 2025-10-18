// API helper con fallback
const ORIGIN = window.location.origin.replace(/\/$/, '');
const EXTERNAL_BASE = (window.PRIZO_API_BASE || '').replace(/\/$/, '') || null;

export async function apiFetch(path, opts = {}) {
  const p = path.startsWith('/') ? path : `/${path}`;
  const urls = [
    EXTERNAL_BASE && EXTERNAL_BASE + p,
    ORIGIN + p,
    ORIGIN + '/api' + p,
  ].filter(Boolean);

  let last;
  for (const url of urls) {
    try {
      const r = await fetch(url, opts);
      if (r.ok) return r;
      last = new Error(`HTTP ${r.status} @ ${url}`);
    } catch (e) { last = e; }
  }
  throw last || new Error('No se pudo contactar API');
}

export const listRaffles = async () => (await (await apiFetch('/raffles/list')).json()).raffles || [];
export const loadConfig  = async (id) => await (await apiFetch(`/config?raffle_id=${encodeURIComponent(id)}`)).json();
export const getProgress = async (id) => (await (await apiFetch(`/raffles/progress?raffle_id=${encodeURIComponent(id)}`)).json()).progress || {};
export const quoteTotal  = async (id, q) => await (await apiFetch('/quote',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({raffle_id:id,quantity:q,method:'pago_movil'})})).json();
export const reserve     = async (id, email, q) => await (await apiFetch('/tickets/reserve',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({raffle_id:id,email,quantity:q})})).json();
export const release     = async (ids)=> apiFetch('/tickets/release',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ticket_ids:ids})});
export const submitPay   = async (payload, hasIds)=> await (await apiFetch(hasIds?'/payments/reserve_submit':'/payments/submit',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)})).json();
export const checkTicket = async (body)=> await (await apiFetch('/tickets/check',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)})).json();
