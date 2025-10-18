import * as API from "./api.js";
import { mountDraw } from "./draw.js";

const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => Array.from(r.querySelectorAll(s));
const safeImg = (url) => {
  try {
    const u = new URL(url);
    return /^https?:$/.test(u.protocol) ? url : null;
  } catch {
    return null;
  }
};

// ----- Estado global
let CONFIG = null, supa = null;
let raffleId = null, qty = 1, reservedIds = [];

// Datos del comprador (SOLO desde el pop-menu; ya NO pedimos email aquí)
let USER_INFO = {
  email: null,           // <- se pedirá en el formulario de pago
  document_id: null,
  state: null,
  phone: null,
};

// ====== Helpers de UI ======
function renderBuyerSummary() {
  $("#sum_email") && ($("#sum_email").textContent = USER_INFO.email || "—");
  $("#sum_doc") && ($("#sum_doc").textContent = USER_INFO.document_id || "—");
  $("#sum_state") && ($("#sum_state").textContent = USER_INFO.state || "—");
  $("#sum_phone") && ($("#sum_phone").textContent = USER_INFO.phone || "—");
}

// ----- Términos
const termsModal = $("#termsModal"),
  chkAccept = $("#chkAccept"),
  btnAccept = $("#btnAccept"),
  btnDecline = $("#btnDecline");
function showTerms() {
  termsModal.classList.remove("hidden");
  document.body.classList.add("no-scroll", "modal-open");
}
function hideTerms() {
  termsModal.classList.add("hidden");
  document.body.classList.remove("no-scroll", "modal-open");
}
chkAccept?.addEventListener("change", () => (btnAccept.disabled = !chkAccept.checked));
btnAccept?.addEventListener("click", () => {
  localStorage.setItem("prizo_terms_accepted", "1");
  hideTerms();
});
btnDecline?.addEventListener("click", () => (location.href = "https://google.com"));
if (!localStorage.getItem("prizo_terms_accepted")) showTerms();

// ----- Selección cantidad (modal fullscreen opcional)
const qtyModal = $("#qtyModal"),
  qtyInput = $("#qtyModalInput");
$("#qtyCancel")?.addEventListener("click", () => qtyModal.classList.add("hidden"));
$$("[data-qty-step]").forEach((b) =>
  b.addEventListener("click", () => {
    qtyInput.value = Math.max(1, (+qtyInput.value || 1) + +b.dataset.qtyStep);
  }),
);
$("#qtyConfirm")?.addEventListener("click", async () => {
  qty = Math.max(1, +qtyInput.value || 1);
  await reserveFlow();
  closeQtys();
  openPayment();
});

// ----- Pop-menu embebido (profesional)
const emb = $("#embeddedQty"),
  embInput = $("#embeddedQtyInput"),
  embEmail = $("#emb_email"),
  embDocId = $("#emb_docId"),
  embState = $("#emb_state"),
  embPhone = $("#emb_phone");

$("#embeddedCancel")?.addEventListener("click", () => {
  emb.classList.add("hidden");
  emb.style.display = "none";
});
$$("[data-emb-step]").forEach((b) =>
  b.addEventListener("click", () => {
    embInput.value = Math.max(1, (+embInput.value || 1) + +b.dataset.embStep);
  }),
);

$("#embeddedContinue")?.addEventListener("click", async () => {
  qty = Math.max(1, +embInput.value || 1);

  // >>> YA NO validamos email aquí (se pedirá más adelante)
  // Lo único obligatorio en el pop-menu: doc/state/phone
  const docVal = (embDocId?.value || "").trim();
  const stateVal = (embState?.value || "").trim();
  const phoneVal = (embPhone?.value || "").trim();

  if (!docVal)  { alert("Por favor ingresa tu cédula / RIF."); embDocId?.focus(); return; }
  if (!stateVal){ alert("Por favor selecciona tu estado.");    embState?.focus(); return; }
  if (!phoneVal || phoneVal.replace(/\D/g, "").length < 7) {
    alert("Por favor ingresa un teléfono válido."); embPhone?.focus(); return;
  }

  USER_INFO.document_id = docVal;
  USER_INFO.state = stateVal;
  USER_INFO.phone = phoneVal;

  try {
    // Reserva sin email real -> usaremos placeholder en reserveFlow
    await reserveFlow(null);
  } catch (e) {
    console.error(e);
    alert(e.message || "No se pudo reservar. Intenta nuevamente.");
    return;
  }

  // Limpia y pasa a pago
  renderBuyerSummary(); // (email seguirá en “—” hasta que lo escriba en el formulario de pago)
  closeQtys();
  refreshProgress();
  quote();
  openPayment();
});

function closeQtys() {
  emb?.classList.add("hidden");
  emb.style && (emb.style.display = "none");
  qtyModal?.classList.add("hidden");
  document.body.classList.remove("no-scroll", "modal-open");
}

// ----- Navegación
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
  drawTitle = $("#drawTitle");

$("#backToList")?.addEventListener("click", () => {
  raffleId = null;
  header.classList.add("hidden");
  nav.style.display = "none";
  Object.values(sections).forEach((s) => s.classList.add("hidden"));
  listSec.classList.remove("hidden");
  homeTitle.classList.remove("hidden");
  drawTitle.classList.add("hidden");
  USER_INFO = { email: null, document_id: null, state: null, phone: null };
  window.scrollTo({ top: 0, behavior: "smooth" });
});

if (nav) {
  const indicator = nav.querySelector(".nav-indicator");
  const move = (btn) => {
    const track = nav.querySelector(".nav-track");
    if (!track || !indicator) return;
    const buttons = $$(".nav-btn", track);
    const idx = buttons.indexOf(btn);
    if (idx < 0) return;
    const seg = track.getBoundingClientRect().width / buttons.length;
    const width = Math.max(110, seg - 24);
    const left = seg * idx + (seg - width) / 2;
    indicator.style.width = `${width}px`;
    indicator.style.transform = `translateX(${left}px)`;
  };
  $$(".nav-btn", nav).forEach((btn) =>
    btn.addEventListener("click", () => {
      $$(".nav-btn", nav).forEach((b) => b.classList.remove("active"));
      btn.classList.add("active");
      move(btn);
      Object.values(sections).forEach((s) => s.classList.add("hidden"));
      drawTitle.classList.add("hidden");
      const t = btn.dataset.target;
      if (t === "buy") sections.buy.classList.remove("hidden");
      if (t === "verify") sections.verify.classList.remove("hidden");
      if (t === "draw") {
        sections.draw.classList.remove("hidden");
        drawTitle.classList.remove("hidden");
      }
      window.scrollTo({ top: 0, behavior: "smooth" });
    }),
  );
  window.addEventListener("resize", () => {
    const active = nav.querySelector(".nav-btn.active");
    active && move(active);
  });
}

function showBuy() {
  Object.values(sections).forEach((s) => s.classList.add("hidden"));
  sections.buy.classList.remove("hidden");
  refreshProgress();
  quote();
}

// ----- Listado
(async function loadRaffles() {
  try {
    err.style.display = "none";
    noR.style.display = "none";
    grid.innerHTML = "";
    skel.style.display = "grid";
    const list = await API.listRaffles();
    grid.innerHTML = "";
    skel.style.display = "none";
    if (!list.length) {
      noR.style.display = "block";
      return;
    }
    list.forEach((x) => {
      const card = document.createElement("button");
      card.className = "raffle-card";
      card.type = "button";
      const img = safeImg(x.image_url);
      card.innerHTML = `
        ${img ? `<div class="cover-wrap"><img class="cover" src="${img}" alt="${x.name}" loading="lazy"/></div>` : ""}
        <div class="title">${x.name}</div>
        <div class="meta">${x.description || ""}<div class="sep"></div>
          <span class="pill">Precio: ${(x.ticket_price_cents / 100).toFixed(2)} ${x.currency || "USD"}</span>
        </div>`;
      card.addEventListener("click", () => selectRaffle(x));
      grid.appendChild(card);
    });
  } catch (e) {
    console.error(e);
    skel.style.display = "none";
    err.style.display = "block";
  }
})();

async function selectRaffle(x) {
  raffleId = x.id;
  qty = 1;
  reservedIds = [];
  USER_INFO = { email: null, document_id: null, state: null, phone: null };

  listSec.classList.add("hidden");
  header.classList.remove("hidden");
  nav.style.display = "";
  homeTitle.classList.add("hidden");
  nameEl.textContent = x.name;

  CONFIG = await API.loadConfig(raffleId);
  metaEl.textContent = CONFIG.ves_price_per_ticket
    ? `Ticket: ${CONFIG.ves_price_per_ticket.toFixed(2)} Bs (tasa del día)`
    : "";
  const img = safeImg(CONFIG.image_url || x.image_url);
  if (img) {
    coverImg.src = img;
    coverImg.alt = x.name;
    coverWrap.classList.remove("hidden");
  } else coverWrap.classList.add("hidden");

  renderProgress(CONFIG.progress);
  showBuy();
  nav.querySelector('.nav-btn[data-target="buy"]')?.classList.add("active");
  setTimeout(() => window.dispatchEvent(new Event("resize")), 40);
  setTimeout(() => {
    openEmbedded(qty);
  }, 80);
}

// ----- Config / progress / quote
function renderProgress(p) {
  if (!p || p.total == null) {
    pWrap.classList.add("hidden");
    return;
  }
  pWrap.classList.remove("hidden");
  const v = typeof p.percent_sold === "number" ? p.percent_sold : p.total ? (100 * (p.sold || 0)) / p.total : 0;
  const vClamped = Math.max(0, Math.min(100, v));
  pFill.style.width = `${vClamped}%`;
  pFillLbl.textContent = `${vClamped.toFixed(1)}%`;
  pPct.textContent = `${vClamped.toFixed(1)}%`;
}
async function refreshProgress() {
  if (!raffleId) return;
  renderProgress(await API.getProgress(raffleId));
}

function clamp(q) {
  const p = CONFIG?.progress;
  if (!p || p.total == null || p.remaining == null) return Math.max(1, Math.min(50, q)); // límite 50
  return Math.max(1, Math.min(50, Math.min(q, p.remaining || 1)));
}
async function quote() {
  if (!raffleId || !CONFIG) return;
  qty = clamp(qty);
  $("#qtySummary").textContent = String(qty);
  const notice = $("#methodNotice");
  notice.classList.remove("warn");
  notice.textContent = "El monto en Bs se calcula a la tasa del día.";
  try {
    const d = await API.quoteTotal(raffleId, qty);
    if (d.error) {
      $("#ves").value = "";
      notice.textContent = d.error;
      return;
    }
    $("#ves").value = typeof d.total_ves === "number" ? d.total_ves.toFixed(2) : "";
  } catch {
    $("#ves").value = "";
    notice.textContent = "No se pudo cotizar. Reintenta.";
  }
}

// ----- Pago
let tId = null,
  remaining = 0;
function formatTime(s) {
  const m = String(Math.floor(s / 60)).padStart(2, "0"),
    n = String(Math.floor(s % 60)).padStart(2, "0");
  return `${m}:${n}`;
}
function tick() {
  const el = $("#paymentTimerValue"),
    wrap = $("#paymentTimer");
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
    if (!remaining) {
      cancelPayment("Tiempo expirado — la operación fue cancelada.");
    }
  }, 1000);
}
function stopTimer() {
  if (tId) {
    clearInterval(tId);
    tId = null;
  }
}
function cancelPayment(msg) {
  $("#paymentArea")?.classList.add("hidden");
  stopTimer();
  if (reservedIds?.length) {
    API.release(reservedIds).catch(() => {});
    reservedIds = [];
  }
  const m = $("#buyMsg");
  if (m) {
    m.textContent = `❌ ${msg || "Operación cancelada"}`;
    m.style.color = "#ffd6dd";
  }
}

function openEmbedded(q = 1) {
  const em = emb;
  if (!em) return;
  em.style.display = "";
  em.classList.remove("hidden");
  embInput.value = Math.max(1, q);
  embInput.focus();
}
function openPayment() {
  // Ya NO exigimos email previo; solo que existan doc/state/phone
  if (!USER_INFO.document_id || !USER_INFO.state || !USER_INFO.phone) {
    openEmbedded(qty);
    return;
  }
  $("#paymentArea")?.classList.remove("hidden");
  $("#summaryBox").style.display = "";
  $("#qtySummary").textContent = String(qty);
  renderPM();
  renderBuyerSummary();
  quote();
  startTimer(10 * 60);

  // Refleja en el resumen el email que el usuario escriba en el formulario de pago
  const emailInput = $("#email");
  if (emailInput) {
    emailInput.addEventListener("input", () => {
      USER_INFO.email = (emailInput.value || "").trim() || null;
      renderBuyerSummary();
    });
  }
}
function renderPM() {
  const itemsWrap = $("#methodItems"),
    status = $("#methodStatus");
  itemsWrap.innerHTML = "";
  status.style.display = "none";
  const pm = CONFIG?.payment_methods?.pago_movil;
  let conf = false;
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
  try {
    const t = await navigator.clipboard.readText();
    const ref = $("#reference");
    ref.value = t.trim();
    ref.focus();
  } catch {}
});

async function serverUpload(file) {
  if (!file) return null;
  const bases = [window.PRIZO_API_BASE, window.location.origin, window.location.origin + "/api"]
    .filter(Boolean)
    .map((b) => String(b).replace(/\/$/, ""));
  for (const b of bases) {
    try {
      const fd = new FormData();
      fd.append("file", file);
      const r = await fetch(b + "/payments/upload_evidence", { method: "POST", body: fd });
      if (r.ok) {
        const j = await r.json();
        if (j?.secure_url) return j.secure_url;
      }
    } catch {}
  }
  return null;
}

// Reserva usando email real si viene; si no, placeholder
async function reserveFlow(emailMaybe) {
  const email =
    (emailMaybe && /^\S+@\S+\.\S+$/.test(emailMaybe) ? emailMaybe : `guest+${Date.now()}@example.invalid`);

  try {
    const { tickets = [] } = await API.reserve(raffleId, email, qty);
    reservedIds = tickets.map((t) => t.id);
  } catch (e) {
    const msg = e?.message || "No se pudo reservar.";
    throw new Error(msg);
  }
}

$("#payBtn")?.addEventListener("click", async () => {
  const msg = $("#buyMsg");
  try {
    if (!raffleId) throw new Error("Primero selecciona una rifa.");
    if (!CONFIG?.raffle_active) throw new Error("Esta rifa no está activa.");

    // Email ahora VIENE DEL FORMULARIO DE PAGO
    const email = ($("#email")?.value || "").trim();
    const reference = ($("#reference")?.value || "").trim();
    const file = $("#evidence")?.files?.[0];

    if (!/^\S+@\S+\.\S+$/.test(email)) throw new Error("Ingresa un email válido.");
    if (!USER_INFO.document_id) throw new Error("La cédula / RIF es obligatoria.");
    if (!USER_INFO.state) throw new Error("El estado es obligatorio.");
    if (!USER_INFO.phone) throw new Error("El teléfono es obligatorio.");
    if (!reference) throw new Error("La referencia es obligatoria.");

    $("#payBtn").classList.add("is-busy");
    $("#payBtn").disabled = true;
    msg.textContent = "Enviando pago...";
    msg.style.color = "";

    // Subida del comprobante
    let evidence_url = file ? await serverUpload(file) : null;
    if (!evidence_url && file && CONFIG?.supabase_url && CONFIG?.public_anon_key) {
      supa = supa || window.supabase?.createClient(CONFIG.supabase_url, CONFIG.public_anon_key);
      const bucket = CONFIG.payments_bucket || "payments";
      const path = `evidences/${Date.now()}_${file.name}`.replace(/\s+/g, "_");
      const { error } = await supa.storage.from(bucket).upload(path, file, { upsert: true });
      if (error) throw new Error("No se pudo subir el comprobante");
      const { data: pub } = supa.storage.from(bucket).getPublicUrl(path);
      evidence_url = pub.publicUrl;
    }

    const payload = {
      raffle_id: raffleId,
      email,
      reference,
      evidence_url,
      ticket_ids: reservedIds,     // si hubo reserva previa
      method: "pago_movil",
      quantity: qty,               // informativo
      // Datos del comprador (del pop-menu)
      document_id: USER_INFO.document_id,
      state: USER_INFO.state,
      phone: USER_INFO.phone,
    };

    const d = await API.submitPay(payload, !!(reservedIds && reservedIds.length));
    if (!("payment_id" in d)) throw new Error(d.detail || "No se pudo registrar el pago");

    msg.textContent = "✅ Pago registrado. Verificación 24–48h.";
    msg.style.color = "";
    reservedIds = [];
    stopTimer();
    await refreshProgress();

    // Reset
    USER_INFO = { email: null, document_id: null, state: null, phone: null };

    // Volver al listado
    setTimeout(() => {
      if (window.history.length > 1) {
        window.history.back();
      }
    }, 1200);

  } catch (e) {
    msg.textContent = `❌ ${e.message}`;
    msg.style.color = "#ffd6dd";
  } finally {
    $("#payBtn").classList.remove("is-busy");
    $("#payBtn").disabled = false;
  }
});

// ----- Verificar
$("#checkBtn")?.addEventListener("click", async () => {
  const body = {
    ticket_number: parseInt($("#chk_ticket")?.value || "") || null,
    reference: ($("#chk_ref")?.value || "").trim() || null,
    email: ($("#chk_email")?.value || "").trim() || null,
  };
  $("#checkOut").textContent = JSON.stringify(await API.checkTicket(body), null, 2);
});

// ----- Sorteo
mountDraw($("#sec-draw"));
