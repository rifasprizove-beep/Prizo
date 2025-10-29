// ---------- Sorteo con CSV (solo frontend) ----------
let participants = [], headers = [];
let shuffleTimer = null, autoStopTimer = null, isShuffling = false;

function parseCSV(text){
  if (text.charCodeAt(0) === 0xFEFF) text = text.slice(1);
  const firstLine = text.split(/\r?\n/)[0] || '';
  const counts = [
    {sep: ',', n: (firstLine.match(/,/g)||[]).length},
    {sep: ';', n: (firstLine.match(/;/g)||[]).length},
    {sep: '\t', n: (firstLine.match(/\t/g)||[]).length},
  ].sort((a,b)=>b.n-a.n);
  const SEP = counts[0].n > 0 ? counts[0].sep : ',';

  const rows = [];
  let row = [], cell = '', inQuotes = false;
  for (let i=0; i<text.length; i++){
    const ch = text[i], nxt = text[i+1];
    if (ch === '"'){
      if (inQuotes && nxt === '"'){ cell += '"'; i++; }
      else inQuotes = !inQuotes;
      continue;
    }
    if (!inQuotes && ch === SEP){ row.push(cell); cell=''; continue; }
    if (!inQuotes && ch === '\n'){ rows.push(row.concat(cell)); row=[]; cell=''; continue; }
    if (!inQuotes && ch === '\r'){ continue; }
    cell += ch;
  }
  if (cell.length || row.length) rows.push(row.concat(cell));
  return rows.map(r => r.map(c => (c ?? '').toString().trim()));
}

function renderSlot(text, highlight=false){
  const bombo = document.getElementById("bombo");
  bombo.innerHTML = '';
  const slot = document.createElement('div');
  slot.className = 'slot animate-in';
  slot.textContent = text;
  bombo.appendChild(slot);
  bombo.classList.toggle('glow', !!highlight);
}

function confettiBurst(n=120){
  for(let i=0;i<n;i++){
    const el = document.createElement('div');
    el.className = 'confetti';
    el.style.setProperty('--x', (Math.random()*100)+'vw');
    el.style.setProperty('--dx', ((Math.random()*40-20))+'vw');
    el.style.setProperty('--r', (Math.random()*360)+'deg');
    el.style.setProperty('--dr', (200+Math.random()*360)+'deg');
    el.style.setProperty('--t', (1.8+Math.random()*1.4)+'s');
    el.style.setProperty('--h', Math.floor(Math.random()*360));
    document.body.appendChild(el);
    setTimeout(()=>el.remove(), 2200);
  }
}
function updateDrawButton(state){
  const btn = document.getElementById("drawToggle");
  if (!btn) return;
  if (state === "running"){ btn.textContent = "Sorteando…"; btn.disabled = true; btn.setAttribute('aria-pressed','true'); }
  else { btn.textContent = "Iniciar sorteo"; btn.disabled = false; btn.setAttribute('aria-pressed','false'); }
}

const fileInput = document.getElementById("csvFile");
const uploadBtn = document.getElementById("uploadBtn");
const fileName = document.getElementById("fileName");
uploadBtn.addEventListener("click", () => fileInput.click());
fileInput.addEventListener("change", () => {
  const file = fileInput.files[0];
  if (!file) return;
  fileName.textContent = file.name;
  const reader = new FileReader();
  reader.onload = (e) => {
    const rows = parseCSV(e.target.result).filter(r => r.length && r.join('').length);
    if (!rows.length) return alert("CSV vacío o no legible.");
    headers = rows[0].map(h => h.replace(/^\"|\"$/g,'').trim());
    participants = rows.slice(1).map(r => { const obj = {}; headers.forEach((h,i)=> obj[h] = (r[i] ?? '').toString().trim()); return obj; });
    const sel = document.getElementById("columnSelect");
    sel.innerHTML = headers.map(h => `<option value="${h}">${h}</option>`).join("");
    sel.disabled = false;
    clearInterval(shuffleTimer); clearTimeout(autoStopTimer); isShuffling = false;
    document.getElementById("winners").innerHTML = "";
    document.getElementById("bombo").classList.remove("spin");
    renderSlot("Listo para iniciar ▶");
    document.getElementById("live").textContent = `Archivo cargado con ${participants.length} participantes.`;
    updateDrawButton("idle");
  };
  reader.readAsText(file);
});
function startShuffle(){
  if (!participants.length) return alert("Primero carga un archivo CSV.");
  const col = document.getElementById("columnSelect").value || headers[0];
  if (isShuffling) return;
  isShuffling = true;
  document.getElementById('bombo').classList.add('spin');
  document.getElementById('live').textContent = "🎥 Sorteo iniciado...";
  shuffleTimer = setInterval(()=>{
    const p = participants[(Math.random()*participants.length)|0];
    const txt = `${p[col]}${p["Instagram"] ? " ("+p["Instagram"]+")" : ""}`;
    renderSlot(txt, false);
  }, 80);
  clearTimeout(autoStopTimer);
  autoStopTimer = setTimeout(stopAndPick, 5000);
  updateDrawButton("running");
}
function stopAndPick(){
  if (!participants.length) return;
  const col = document.getElementById("columnSelect").value || headers[0];
  if (!isShuffling) return;
  const bombo = document.getElementById("bombo");
  clearInterval(shuffleTimer); clearTimeout(autoStopTimer);
  const steps = 10; let i = 0;
  function decelStep(delay){
    setTimeout(()=>{
      const p = participants[(Math.random()*participants.length)|0];
      const txt = `${p[col]}${p["Instagram"] ? " ("+p["Instagram"]+")" : ""}`;
      renderSlot(txt, false); i++;
      if (i < steps){ decelStep(delay + 60); }
      else {
        const w = participants[(Math.random()*participants.length)|0];
        const finalText = `${w[col]}${w["Instagram"] ? " ("+w["Instagram"]+")" : ""}`;
        renderSlot(finalText, true);
        bombo.classList.remove('spin');
        document.getElementById("live").textContent = `🎉 ¡Ganador: ${finalText}!`;
        const li = document.createElement('li');
        li.textContent = finalText;
        document.getElementById('winners').prepend(li);
        confettiBurst(140); isShuffling = false; updateDrawButton("idle");
      }
    }, delay);
  }
  decelStep(80);
}

document.getElementById("drawToggle").addEventListener("click", () => {
  if (!participants.length) { alert("Primero sube un CSV."); return; }
  if (!isShuffling) startShuffle();
});
