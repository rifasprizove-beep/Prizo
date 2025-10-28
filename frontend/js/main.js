// /static/js/main.js  — PRIZO • actualizado 2025-10-28 (reserva persistente + fix liberar/submit)
import * as API from "./api.js";
import { mountDraw } from "./draw.js";

const VERSION = "20251028h";

// ==== Utils ====
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
const safeImg = (url) => {
  try { const u = new URL(url); return /^https?:$/.test(u.protocol) ? url : null; }
  catch { return null; }
};
// Transformador Cloudinary: añade f_auto,q_auto y ancho máximo (c_limit)
function cld(url, w) {
  if (!url) return null;
  try {
    const u = new URL(url);
    if (!/res\.cloudinary\.com/.test(u.hostname)) return url;
    const parts = u.pathname.split("/");
    const i = parts.findIndex(p => p === "upload");
    if (i === -1) return url;
    const trans = [`f_auto`, `q_auto`].concat(w ? [`w_${Math.max(80, +w|0)}`, `c_limit`] : []);
    const hasTransform = parts[i+1] && !/^v\d+/.test(parts[i+1]);
    if (hasTransform) {
      parts[i+1] = `${trans.join(",")},${parts[i+1]}`;
    } else {
      parts.splice(i+1, 0, trans.join(","));
    }
    u.pathname = parts.join("/");
    return u.toString();
  } catch { return url; }
}
// Debounce simple
const debounce = (fn, ms = 120) => { let t; return (...args) => { clearTimeout(t); t = setTimeout(() => fn(...args), ms); }; };

// ----- Estado global -----
let CONFIG = null, supa = null;
let raffleId = null, qty = 1, reservedIds = [], holdId = null;

// ====== RESERVA PERSISTENTE (para no perderla por pestañas/diálogos) ======
const HOLD_KEY = "prizo_hold_v1";

function saveHold(hold) {
  // hold: { hold_id, ticket_ids, expires_at }
  try { sessionStorage.setItem(HOLD_KEY, JSON.stringify(hold)); } catch {}
}
function loadHold() {
  try {
    const raw = sessionStorage.getItem(HOLD_KEY);
    if (!raw) return null;
    const h = JSON.parse(raw);
    if (!h?.hold_id || !Array.isArray(h.ticket_ids) || !h.ticket_ids.length) return null;
    return h;
  } catch { return null; }
}
function clearHold() { try { sessionStorage.removeItem(HOLD_KEY); } catch {} }
function nowTs() { return Date.now(); }
function isHoldAlive(h) { return !!h && nowTs() < (h.expires_at || 0); }

// Datos del comprador (se piden SOLO en el formulario de pago)
let USER_INFO = { email: null, document_id: null, state: null, phone: null };

// ====== Helpers UI ======
function renderBuyerSummary() {
  $("#sum_email") && ($("#sum_email").textContent = USER_INFO.email || "—");
  $("#sum_doc") && ($("#sum_doc").textContent = USER_INFO.document_id || "—");
  $("#sum_state") && ($("#sum_state").textContent = USER_INFO.state || "—");
  $("#sum_phone") && ($("#sum_phone").textContent = USER_INFO.phone || "—");
}

// Loader global
function showLoading(msg = "Cargando…") {
  const o = $("#appLoading"); const t = $("#appLoadingMsg");
  if (t) t.textContent = msg;
  if (o) o.classList.remove("hidden");
}
function hideLoading() { $("#appLoading")?.classList.add("hidden"); }

// ----- Términos -----
const termsModal = $("#termsModal"),
  chkAccept = $("#chkAccept"),
  btnAccept = $("#btnAccept"),
  btnDecline = $("#btnDecline");

function showTerms() { termsModal?.classList.remove("hidden"); document.body.classList.add("no-scroll","modal-open"); }
function hideTerms() { termsModal?.classList.add("hidden"); document.body.classList.remove("no-scroll","modal-open"); }

chkAccept?.addEventListener("change", () => (btnAccept.disabled = !chkAccept.checked));
btnAccept?.addEventListener("click", () => { localStorage.setItem("prizo_terms_accepted","1"); hideTerms(); });
btnDecline?.addEventListener("click", () => (location.href = "https://google.com"));
if (!localStorage.getItem("prizo_terms_accepted")) showTerms();

// ----- Modales de cantidad -----
const qtyModal = $("#qtyModal"), qtyInput = $("#qtyModalInput");
$("#qtyCancel")?.addEventListener("click", () => qtyModal?.classList.add("hidden"));
$$("[data-qty-step]").forEach((b) => b.addEventListener("click", () => {
  qtyInput.value = Math.max(1, (+qtyInput.value || 1) + +b.dataset.qtyStep);
}));
$("#qtyConfirm")?.addEventListener("click", async () => {
  qty = Math.max(1, +qtyInput.value || 1);
  await reserveFlow();
  closeQtys();
  openPayment();
});

// Pop-menu embebido (solo cantidad)
const emb = $("#embeddedQty"), embInput = $("#embeddedQtyInput");
$("#embeddedCancel")?.addEventListener("click", () => {
  emb?.classList.add("hidden"); if (emb) emb.style.display = "none";
});
$$("[data-emb-step]").forEach((b) => b.addEventListener("click", () => {
  embInput.value = Math.max(1, (+embInput.value || 1) + +b.dataset.embStep);
}));
$("#embeddedContinue")?.addEventListener("click", async () => {
  qty = Math.max(1, +embInput.value || 1);
  try { await reserveFlow(); }
  catch (e) { console.error(e); alert(e.message || "No se pudo reservar. Intenta nuevamente."); return; }
  closeQtys();
  refreshProgress(); quoteDebounced(); openPayment();
});

function closeQtys() {
  emb?.classList.add("hidden"); if (emb) emb.style.display = "none";
  qtyModal?.classList.add("hidden");
  document.body.classList.remove("no-scroll","modal-open");
}

// ====== RESET FUERTE DE PAGO / FORM ======
let tId = null, remaining = 0;

function resetPaymentUI() {
  $("#paymentArea")?.classList.add("hidden");
  const bh = $("#buyHead"); if (bh) bh.style.display = "none";
  $("#summaryBox") && ($("#summaryBox").style.display = "none");
  ["email","reference","docId","state","phone"].forEach(id => { const el = $("#" + id); if (el) el.value = ""; });
  const ev = $("#evidence"); if (ev) ev.value = "";
  const msg = $("#buyMsg"); if (msg) { msg.textContent = ""; msg.style.color = ""; }
  const itemsWrap = $("#methodItems"); if (itemsWrap) itemsWrap.innerHTML = "";
  const status = $("#methodStatus"); if (status) status.style.display = "none";
  renderBuyerSummary();
  stopTimer();
  // libera en backend si había (pero NO lo hagas por visibilitychange)
  if (reservedIds?.length) { API.release(reservedIds).catch(() => {}); }
  reservedIds = []; holdId = null; clearHold();
  closeQtys();
}

// ----- Navegación / layout -----
const homeTitle = $("#homeTitle"),
  listSec = $("#raffleList"),
  grid = $("#rafflesGrid"),
  skel = $("#rafflesSkeleton"),
  noR = $("#noRaffles"),
  err = $("#rafflesError");

const header = $("#raffleHeader"),
  nameEl = $("#raffleName"),
  metaEl = $("#raffleMeta"),
  coverWrap = $("#raffleCover"),
  coverImg = $("#raffleCoverImg");

const pWrap = $("#progressWrap"),
  pFill = $("#progressFill"),
  pPct = $("#progressPct"),
  pFillLbl = $("#progressFillLabel");

const nav = $("#raffleNav"),
  sections = { buy: $("#sec-buy"), verify: $("#sec-verify"), draw: $("#sec-draw") },
  drawTitle = $("#drawTitle"),
  buyHead = $("#buyHead");

function goHome() {
  resetPaymentUI();
  qty = 1; raffleId = null;
  USER_INFO = { email: null, document_id: null, state: null, phone: null };
  Object.values(sections).forEach((s) => s?.classList.add("hidden"));
  header?.classList.add("hidden");
  if (nav) {
    nav.style.display = "none";
    $$(".nav-btn", nav).forEach((b) => b.classList.remove("active"));
  }
  listSec?.classList.remove("hidden");
  homeTitle?.classList.remove("hidden");
  drawTitle?.classList.add("hidden");
  window.scrollTo({ top: 0, behavior: "smooth" });
}
$("#backToList")?.addEventListener("click", () => { goHome(); });

if (nav) {
  const indicator = nav.querySelector(".nav-indicator");
  const move = (btn) => {
    const track = nav.querySelector(".nav-track"); if (!track || !indicator) return;
    const buttons = $$(".nav-btn", track);
    const idx = buttons.indexOf(btn); if (idx < 0) return;
    const seg = track.getBoundingClientRect().width / buttons.length;
    const width = Math.max(110, seg - 24); const left = seg*idx + (seg - width)/2;
    indicator.style.width = `${width}px`; indicator.style.transform = `translateX(${left}px)`;
  };
  $$(".nav-btn", nav).forEach((btn) => btn.addEventListener("click", () => {
    $$(".nav-btn", nav).forEach((b) => b.classList.remove("active"));
    btn.classList.add("active"); move(btn);
    Object.values(sections).forEach((s) => s.classList.add("hidden"));
    drawTitle?.classList.add("hidden");
    const t = btn.dataset.target;
    if (t === "buy") sections.buy.classList.remove("hidden");
    if (t === "verify") sections.verify.classList.remove("hidden");
    if (t === "draw") { sections.draw.classList.remove("hidden"); drawTitle?.classList.remove("hidden"); }
    window.scrollTo({ top: 0, behavior: "smooth" });
  }));
  window.addEventListener("resize", () => {
    const active = nav.querySelector(".nav-btn.active"); if (active) move(active);
  });
}

function showBuy() {
  Object.values(sections).forEach((s) => s.classList.add("hidden"));
  sections.buy.classList.remove("hidden");
  if (buyHead) buyHead.style.display = "none"; // oculta formulario hasta “Continuar”
  refreshProgress(); quoteDebounced();
}

// ====== Listado (con fallback si falla listRaffles) ======
(async function loadRaffles() {
  try {
    err && (err.style.display = "none");
    noR && (noR.style.display = "none");
    grid && (grid.innerHTML = "");
    skel && (skel.style.display = "grid");

    let list = null;
    try {
      list = await API.listRaffles(); // principal
    } catch (e) {
      console.warn("[listRaffles] error:", e);
    }

    // Fallback: usa public_config si no hay lista o viene vacía
    if (!Array.isArray(list) || !list.length) {
      try {
        const cfg = await API.loadConfig(); // <-- NO pasar null
        if (cfg?.raffle_active && cfg?.raffle_id) {
          list = [{
            id: cfg.raffle_id,
            name: cfg.raffle_name || "Sorteo activo",
            description: "",
            image_url: cfg.image_url || null,
          }];
        } else {
          list = [];
        }
      } catch (e) {
        console.warn("[fallback public_config] error:", e);
        list = null; // marca error real
      }
    }

    grid && (grid.innerHTML = "");
    skel && (skel.style.display = "none");

    if (list === null) { // hubo error real de red/back
      err && (err.style.display = "block");
      noR && (noR.style.display = "none");
      return;
    }
    if (!list.length) {
      noR && (noR.style.display = "block");
      err && (err.style.display = "none");
      return;
    }

    list.forEach((x) => {
      const card = document.createElement("button");
      card.className = "raffle-card"; card.type = "button";
      const imgUrl = cld(safeImg(x.image_url), 480);
      const pillId = `pill_${x.id}`;
      card.innerHTML = `
        ${imgUrl ? `<div class="cover-wrap"><img class="cover" src="${imgUrl}" alt="${x.name}" loading="lazy" decoding="async"/></div>` : ""}
        <div class="title">${x.name}</div>
        <div class="meta">${x.description || ""}<div class="sep"></div>
          <span id="${pillId}" class="pill" aria-live="polite">Precio: calculando…</span>
        </div>`;
      card.addEventListener("click", () => selectRaffle(x));
      grid?.appendChild(card);

      // Precio en Bs (sin mostrar USD nunca)
      (async () => {
        try {
          const cfg = await API.loadConfig(x.id);
          const el = document.getElementById(pillId);
          const ves = Number(cfg?.ves_price_per_ticket);
          if (el) el.textContent = (ves && ves > 0) ? `Precio: ${ves.toFixed(2)} Bs` : "Precio: no disponible";
        } catch {
          const el = document.getElementById(pillId);
          if (el) el.textContent = "Precio: no disponible";
        }
      })();
    });
  } catch (e) {
    console.error(e);
    skel && (skel.style.display = "none");
    err && (err.style.display = "block");
    noR && (noR.style.display = "none");
  }
})();

async function selectRaffle(x) {
  try {
    showLoading("Cargando rifa…");
    resetPaymentUI();
    raffleId = x.id; qty = 1;
    USER_INFO = { email: null, document_id: null, state: null, phone: null };

    listSec?.classList.add("hidden");
    header?.classList.remove("hidden");
    nav && (nav.style.display = "");
    homeTitle?.classList.add("hidden");
    nameEl && (nameEl.textContent = x.name);

    CONFIG = await API.loadConfig(raffleId);
    metaEl && (metaEl.textContent =
      (CONFIG?.ves_price_per_ticket != null && Number(CONFIG.ves_price_per_ticket) > 0)
        ? `Ticket: ${(+CONFIG.ves_price_per_ticket).toFixed(2)} Bs (tasa del día)`
        : "Ticket: calculando…"
    );

    const img = cld(safeImg(CONFIG?.image_url || x.image_url), 1100);
    if (img) { if (coverImg) { coverImg.src = img; coverImg.alt = x.name; } coverWrap?.classList.remove("hidden"); }
    else coverWrap?.classList.add("hidden");

    renderProgress(CONFIG?.progress);
    showBuy();
    nav?.querySelector('.nav-btn[data-target="buy"]')?.classList.add("active");
    setTimeout(() => window.dispatchEvent(new Event("resize")), 40);
    setTimeout(() => { openEmbedded(qty); }, 80);
  } finally {
    hideLoading();
  }
}

// ====== Progreso / Cotización ======
function renderProgress(p) {
  if (!p || p.total == null) { pWrap?.classList.add("hidden"); return; }
  pWrap?.classList.remove("hidden");
  const v = typeof p.percent_sold === "number" ? p.percent_sold : p.total ? (100 * (p.sold || 0)) / p.total : 0;
  const vClamped = Math.max(0, Math.min(100, v));
  pFill && (pFill.style.width = `${vClamped}%`);
  pFillLbl && (pFillLbl.textContent = `${vClamped.toFixed(1)}%`);
  pPct && (pPct.textContent = `${vClamped.toFixed(1)}%`);
}
async function refreshProgress() {
  if (!raffleId) return;
  try {
    const p = await API.getProgress(raffleId);
    renderProgress(p);
    if (CONFIG) CONFIG.progress = p;
  } catch {}
}
function clamp(q) {
  const p = CONFIG?.progress;
  const maxPerTxn = 50; // keep per-transaction limit low to avoid abuse
  if (!p || p.total == null || p.remaining == null) return Math.max(1, Math.min(maxPerTxn, q));
  return Math.max(1, Math.min(maxPerTxn, Math.min(q, p.remaining || 1)));
}
const quoteDebounced = debounce(quote, 120);

async function quote() {
  if (!raffleId || !CONFIG) return;
  qty = clamp(qty);
  $("#qtySummary") && ($("#qtySummary").textContent = String(qty));
  const notice = $("#methodNotice");
  notice?.classList.remove("warn");
  if (notice) notice.textContent = "El monto en Bs se calcula a la tasa del día.";
  try {
    const d = await API.quoteTotal(raffleId, qty);
    if (d?.error) { $("#ves") && ($("#ves").value = ""); if (notice) notice.textContent = d.error; return; }
    $("#ves") && ($("#ves").value = typeof d?.total_ves === "number" ? d.total_ves.toFixed(2) : "");
  } catch {
    $("#ves") && ($("#ves").value = ""); if (notice) notice.textContent = "No se pudo cotizar. Reintenta.";
  }
}

// ====== Pago / Temporizador ======
function formatTime(s) {
  const m = String(Math.floor(s/60)).padStart(2,"0"), n = String(Math.floor(s%60)).padStart(2,"0");
  return `${m}:${n}`;
}
function tick() {
  const el = $("#paymentTimerValue"), wrap = $("#paymentTimer");
  if (!el || !wrap) return;
  el.textContent = formatTime(remaining);
  wrap.classList.toggle("hidden", remaining <= 0);
}
function startTimer(sec) {
  clearInterval(tId);
  remaining = Math.max(0, Math.floor(sec));
  tick();
  tId = setInterval(() => {
    remaining = Math.max(0, remaining - 1);
    tick();
    if (!remaining) { cancelPayment("Tiempo expirado — la operación fue cancelada."); }
  }, 1000);
}
function stopTimer() { if (tId) { clearInterval(tId); tId = null; } }

function cancelPayment(msg) {
  resetPaymentUI();
  const m = $("#buyMsg");
  if (m) { m.textContent = `❌ ${msg || "Operación cancelada"}`; m.style.color = "#ffd6dd"; }
  setTimeout(goHome, 800);
}

function openEmbedded(q = 1) {
  const em = emb; if (!em) return;
  em.style.display = ""; em.classList.remove("hidden");
  embInput && (embInput.value = Math.max(1, q));
  embInput?.focus();
  const bh = $("#buyHead"); if (bh) bh.style.display = "none";
}

let cancelListenerBound = false;
let emailListenerBound = false;

function openPayment() {
  const bh = $("#buyHead"); if (bh) bh.style.display = "flex";
  $("#paymentArea")?.classList.remove("hidden");
  $("#summaryBox") && ($("#summaryBox").style.display = "");
  $("#qtySummary") && ($("#qtySummary").textContent = String(qty));
  renderPM(); renderBuyerSummary(); quoteDebounced(); startTimer(10 * 60);

  const emailInput = $("#email");
  if (emailInput && !emailListenerBound) {
    emailListenerBound = true;
    emailInput.addEventListener("input", () => {
      USER_INFO.email = (emailInput.value || "").trim() || null;
      renderBuyerSummary();
    });
  }
  const cancelBtn = $("#cancelPaymentBtn");
  if (cancelBtn && !cancelListenerBound) {
    cancelListenerBound = true;
    cancelBtn.addEventListener("click", () => { window.prizoCancel?.("Operación cancelada por el usuario."); });
  }
}

function renderPM() {
  const itemsWrap = $("#methodItems"), status = $("#methodStatus");
  if (!itemsWrap || !status) return;
  itemsWrap.innerHTML = ""; status.style.display = "none";
  const pm = CONFIG?.payment_methods?.pago_movil; let conf = false;
  if (pm) {
    Object.entries(pm).forEach(([k, v]) => {
      const row = document.createElement("div");
      row.className = "method-row";
      row.innerHTML = `<div class="method-k">${k}</div><div class="method-v">${v}</div>`;
      itemsWrap.appendChild(row);
    });
    conf = Object.keys(pm).length > 0;
  }
  if (!conf) status.style.display = "inline-flex";
}

$("#pasteRef")?.addEventListener("click", async () => {
  try { const t = await navigator.clipboard.readText(); const ref = $("#reference"); if (ref) { ref.value = t.trim(); ref.focus(); } }
  catch {}
});

// Subida de comprobante al backend (que reenvía a Cloudinary). Fallback: Supabase Storage.
async function serverUpload(file) {
  if (!file) return null;
  const bases = [window.PRIZO_API_BASE, window.location.origin, window.location.origin + "/api"]
    .filter(Boolean).map((b) => String(b).replace(/\/$/, ""));
  for (const b of bases) {
    try {
      const fd = new FormData(); fd.append("file", file);
      const r = await fetch(b + "/payments/upload_evidence", { method: "POST", body: fd });
      if (r.ok) { const j = await r.json(); if (j?.secure_url) return j.secure_url; }
    } catch {}
  }
  return null;
}

// Reserva anónima con retry suave
async function reserveFlow() {
  showLoading("Reservando tickets…");
  try {
    let attempt = 0;
    while (attempt < 2) {
      try {
        const { hold_id, tickets = [] } = await API.reserve(raffleId, qty);
        holdId = hold_id || null;
        reservedIds = tickets.map((t) => t.id);

        // ===== guarda expiración mínima entre tickets =====
        const expires_at = tickets
          .map(t => new Date(t.reserved_until).getTime())
          .reduce((min, ts) => Math.min(min, ts), Infinity);
        saveHold({ hold_id: holdId, ticket_ids: reservedIds, expires_at });

        return;
      } catch (e) {
        attempt++;
        const msg = (e?.message || "").toLowerCase();
        const transient = msg.includes("temporarily unavailable") || msg.includes("eagain") || msg.includes("timeout");
        if (attempt < 2 && transient) { await new Promise(r => setTimeout(r, 150)); continue; }
        throw e;
      }
    }
  } finally {
    hideLoading();
  }
}

// ====== Enviar pago (si hay reserva viva, SIEMPRE reserve_submit) ======
$("#payBtn")?.addEventListener("click", async () => {
  const msg = $("#buyMsg");
  try {
    if (!raffleId) throw new Error("Primero selecciona una rifa.");
    if (!CONFIG?.raffle_active) throw new Error("Esta rifa no está activa.");

    const email = ($("#email")?.value || "").trim();
    const reference = ($("#reference")?.value || "").trim();
    const file = $("#evidence")?.files?.[0];

    if (!/^\S+@\S+\.\S+$/.test(email)) throw new Error("Ingresa un email válido.");
    const docVal = ($("#docId")?.value || "").trim();
    const stateVal = ($("#state")?.value || "").trim();
    const phoneVal = ($("#phone")?.value || "").trim();
    if (!docVal) throw new Error("La cédula / RIF es obligatoria.");
    if (!stateVal) throw new Error("El estado es obligatorio.");
    if (!phoneVal || phoneVal.replace(/\D/g,"").length < 7) throw new Error("El teléfono es obligatorio.");
    if (!reference) throw new Error("La referencia es obligatoria.");

    USER_INFO.email = email; USER_INFO.document_id = docVal; USER_INFO.state = stateVal; USER_INFO.phone = phoneVal;

    $("#payBtn")?.classList.add("is-busy"); if ($("#payBtn")) $("#payBtn").disabled = true;
    if (msg) { msg.textContent = "Enviando pago..."; msg.style.color = ""; }

    // Subir comprobante (server -> Cloudinary) o fallback Supabase Storage
    let evidence_url = file ? await serverUpload(file) : null;
    if (!evidence_url && file && CONFIG?.supabase_url && CONFIG?.public_anon_key && window.supabase) {
      supa = supa || window.supabase.createClient(CONFIG.supabase_url, CONFIG.public_anon_key);
      const bucket = CONFIG.payments_bucket || "payments";
      const path = `evidences/${Date.now()}_${file.name}`.replace(/\s+/g, "_");
      const { error } = await supa.storage.from(bucket).upload(path, file, { upsert: true });
      if (error) throw new Error("No se pudo subir el comprobante");
      const { data: pub } = supa.storage.from(bucket).getPublicUrl(path);
      evidence_url = pub.publicUrl;
    }

    // ===== Recupera hold de memoria o de sessionStorage =====
    let effectiveHold = null;
    if (reservedIds?.length && holdId) {
      // memoria
      effectiveHold = { hold_id: holdId, ticket_ids: reservedIds, expires_at: nowTs() + remaining*1000 };
    } else {
      // storage
      const h = loadHold();
      if (h && isHoldAlive(h)) {
        effectiveHold = h;
        holdId = h.hold_id;
        reservedIds = h.ticket_ids.slice();
      }
    }

    const hasReservation = !!(effectiveHold && isHoldAlive(effectiveHold));

    const payload = {
      raffle_id: raffleId,
      email, reference, evidence_url,
      method: "pago_movil",
      document_id: USER_INFO.document_id, state: USER_INFO.state, phone: USER_INFO.phone,
    };

    let d;
    if (hasReservation) {
      // **SIEMPRE reserve_submit si hay hold vivo**
      payload.ticket_ids = reservedIds;
      payload.hold_id = holdId;
      d = await API.submitPay(payload, true);
    } else {
      // SIN reserva → /payments/submit (multipart requiere quantity)
      const fd = new FormData();
      fd.append("raffle_id", raffleId || "");
      fd.append("email", email);
      fd.append("reference", reference);
      fd.append("method", "pago_movil");
      fd.append("document_id", USER_INFO.document_id || "");
      fd.append("state", USER_INFO.state || "");
      fd.append("phone", USER_INFO.phone || "");
      fd.append("quantity", String(qty || 1));
      if (evidence_url) fd.append("evidence_url", evidence_url);
      if (file) fd.append("file", file);
      const r = await API.apiFetch("/payments/submit", { method: "POST", body: fd });
      d = await (r.headers.get("content-type")||"").includes("json") ? r.json() : { ok: r.ok };
    }

    if (!d || !("payment_id" in d)) throw new Error(d?.detail || d?.error || "No se pudo registrar el pago");

    if (msg) { msg.textContent = "✅ Pago registrado. Verificación 24–48h."; msg.style.color = ""; }
    resetPaymentUI();
    await refreshProgress();
    setTimeout(goHome, 800);
  } catch (e) {
    if (msg) { msg.textContent = `❌ ${e.message}`; msg.style.color = "#ffd6dd"; }
  } finally {
    $("#payBtn")?.classList.remove("is-busy"); if ($("#payBtn")) $("#payBtn").disabled = false;
  }
});

// ----- Verificar -----
$("#checkBtn")?.addEventListener("click", async () => {
  const body = {
    ticket_number: parseInt($("#chk_ticket")?.value || "") || null,
    reference: ($("#chk_ref")?.value || "").trim() || null,
    email: ($("#chk_email")?.value || "").trim() || null,
  };
  const out = await API.checkTicket(body);
  $("#checkOut") && ($("#checkOut").textContent = JSON.stringify(out, null, 2));
});

// ----- Sorteo -----
mountDraw($("#sec-draw"));

// Expone cancelación global (botón en el HTML)
window.prizoCancel = (msg) => cancelPayment(msg || "Operación cancelada por el usuario.");

// Libera reservas SOLO al salir realmente de la página (evitar file-picker/alt-tab)
function releaseIfAny() {
  const h = loadHold();
  const ids = (reservedIds?.length ? reservedIds : (h?.ticket_ids || []));
  if (ids.length) { API.release(ids).catch(() => {}); }
  reservedIds = []; holdId = null; clearHold();
}
window.addEventListener("beforeunload", releaseIfAny);
window.addEventListener("pagehide", releaseIfAny);
// ⚠️ Eliminado: document.visibilitychange (causaba liberaciones al abrir el selector de archivos)

// Versión para depurar caché
console.log("PRIZO_MAIN_VERSION", VERSION);
