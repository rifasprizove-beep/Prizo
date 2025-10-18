export function mountDraw(root){
  const fileInput = root.querySelector('#csvFile');
  const pickBtn   = root.querySelector('#uploadBtn');
  const fileName  = root.querySelector('#fileName');
  const columnSel = root.querySelector('#columnSelect');
  const bombo     = root.querySelector('#bombo');
  const live      = root.querySelector('#live');
  const drawBtn   = root.querySelector('#drawToggle');

  let participants=[], headers=[], isShuffling=false, timer=null, autoStop=null;

  const parseCSV = (text)=>{
    if (text.charCodeAt(0)===0xFEFF) text = text.slice(1);
    const first = text.split(/\r?\n/)[0] || '';
    const SEP = [',',';','\t'].map(s=>({s,c:(first.match(new RegExp(`\\${s}`,'g'))||[]).length})).sort((a,b)=>b.c-a.c)[0].s;
    const out=[], row=[], push=()=>{out.push(row.slice()); row.length=0};
    let cell='', q=false;
    for(let i=0;i<text.length;i++){
      const ch=text[i], nx=text[i+1];
      if(ch==='"'){ if(q && nx==='"'){ cell+='"'; i++; } else q=!q; continue; }
      if(!q && ch===SEP){ row.push(cell.trim()); cell=''; continue; }
      if(!q && (ch==='\n')){ row.push(cell.trim()); cell=''; push(); continue; }
      if(!q && ch==='\r') continue;
      cell+=ch;
    }
    if(cell.length || row.length){ row.push(cell.trim()); push(); }
    return out;
  };

  const render = (t, glow=false)=>{ bombo.innerHTML = `<div class="slot${glow?' glow':''}">${t}</div>`; };

  function startShuffle(){
    if(!participants.length) return alert('Primero sube un CSV.');
    const col = columnSel.value || headers[0];
    if(isShuffling) return;
    isShuffling = true; live.textContent = '🎥 Sorteo iniciado...';
    timer = setInterval(()=>{
      const p = participants[(Math.random()*participants.length)|0];
      render(`${p[col]}${p.Instagram?` (${p.Instagram})`:''}`);
    },80);
    clearTimeout(autoStop); autoStop = setTimeout(stopAndPick, 5000);
    drawBtn.disabled = true; drawBtn.textContent='Sorteando…'; drawBtn.setAttribute('aria-pressed','true');
  }

  function stopAndPick(){
    clearInterval(timer); clearTimeout(autoStop);
    const col = columnSel.value || headers[0];
    let i=0; (function decel(d=80){
      setTimeout(()=>{
        const p = participants[(Math.random()*participants.length)|0];
        render(`${p[col]}${p.Instagram?` (${p.Instagram})`:''}`);
        if(++i<10) decel(d+60);
        else{
          const w = participants[(Math.random()*participants.length)|0];
          render(`${w[col]}${w.Instagram?` (${w.Instagram})`:''}`, true);
          live.textContent = `🎉 ¡Ganador: ${w[col]}!`;
          isShuffling = false; drawBtn.disabled=false; drawBtn.textContent='Iniciar sorteo'; drawBtn.setAttribute('aria-pressed','false');
        }
      }, d);
    })();
  }

  pickBtn.addEventListener('click', ()=> fileInput.click());
  fileInput.addEventListener('change', ()=>{
    const f=fileInput.files[0]; if(!f) return;
    fileName.textContent=f.name;
    const r=new FileReader();
    r.onload=e=>{
      const rows = parseCSV(e.target.result).filter(r=>r.length && r.join('').length);
      if(!rows.length) return alert('CSV vacío o no legible.');
      headers = rows[0].map(h=>h.replace(/^\"|\"$/g,'').trim());
      participants = rows.slice(1).map(r=>{const o={}; headers.forEach((h,i)=>o[h]=(r[i]??'').toString().trim()); return o;});
      columnSel.innerHTML = headers.map(h=>`<option value="${h}">${h}</option>`).join('');
      columnSel.disabled = false;
      render('Listo para iniciar ▶'); live.textContent = `Archivo cargado con ${participants.length} participantes.`;
    };
    r.readAsText(f);
  });

  drawBtn.addEventListener('click', ()=> { if(!isShuffling) startShuffle(); });
}
