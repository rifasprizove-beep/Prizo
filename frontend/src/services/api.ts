const API_BASE = import.meta.env.VITE_API_BASE || '';

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers || {}) },
    ...init,
  });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json() as Promise<T>;
}

export const getRaffles = () =>
  api<any[]>('/raffles/list');

export const getConfig = (raffleId: string) =>
  api<any>(`/config?raffle_id=${encodeURIComponent(raffleId)}`);

export const getProgress = (raffleId: string) =>
  api<any>(`/raffles/progress?raffle_id=${encodeURIComponent(raffleId)}`);

export const postQuote = (body: any) =>
  api<any>('/quote', { method: 'POST', body: JSON.stringify(body) });

export const reserveTickets = (body: any) =>
  api<any>('/tickets/reserve', { method: 'POST', body: JSON.stringify(body) });

export const releaseTickets = (body: any) =>
  api<any>('/tickets/release', { method: 'POST', body: JSON.stringify(body) });

export const checkTickets = (body: any) =>
  api<any>('/tickets/check', { method: 'POST', body: JSON.stringify(body) });

export const submitPayment = (body: any) =>
  api<any>('/payments/submit', { method: 'POST', body: JSON.stringify(body) });

export const submitReservedPayment = (body: any) =>
  api<any>('/payments/reserve_submit', { method: 'POST', body: JSON.stringify(body) });

// Evidencia (si el backend recibe multipart en /payments/upload_evidence):
export async function uploadEvidence(file: File) {
  const form = new FormData();
  form.append('file', file);
  const res = await fetch(`${API_BASE}/payments/upload_evidence`, { method: 'POST', body: form });
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`);
  return res.json();
}
