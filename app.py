from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List, Optional
import uvicorn
import typer

from logic import Raffle
from settings import settings

# --- FastAPI + Typer ---
app = FastAPI(title="Sorteos CSV", version="1.1.0")
cli = typer.Typer(add_completion=False)

# Static (CSS/JS)
app.mount("/static", StaticFiles(directory="static"), name="static")

# Cargar al iniciar (usa tu CSV de env)
raffle = Raffle.from_csv(settings.CSV_PATH, sep=settings.CSV_SEP, encoding=settings.CSV_ENCODING)

# --------- MODELOS ----------
class DrawRequest(BaseModel):
    column: str
    n: int = 1
    unique: bool = True
    seed: Optional[int] = None
    include: Optional[List[str]] = None
    exclude: Optional[List[str]] = None
    dropna: bool = True

class DrawResponse(BaseModel):
    winners: List[str]

# --------- RUTAS API ----------
@app.get("/health")
async def health():
    return {"status": "ok"}

@app.get("/columns")
async def columns():
    # soporta tanto la versión con pandas como la versión sin pandas (propiedad .columns)
    cols = getattr(raffle, "columns", None)
    if cols is None:
        # fallback si fuese un DataFrame con .df
        cols = list(raffle.df.columns)
    return {"columns": list(cols)}

@app.post("/draw", response_model=DrawResponse)
async def draw(req: DrawRequest):
    try:
        winners = raffle.draw(
            column=req.column,
            n=req.n,
            unique=req.unique,
            seed=req.seed,
            include=req.include,
            exclude=req.exclude,
            dropna=req.dropna,
        )
        return DrawResponse(winners=winners)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# --------- PÁGINA WEB ----------
# Página simple sin Jinja (renderizamos HTML aquí mismo para que sea 1 archivo),
# pero usando fetch para llamar a /columns y /draw.
@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return """
<!doctype html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <title>Sorteos CSV</title>
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <link rel="stylesheet" href="/static/style.css">
</head>
<body>
  <main class="container">
    <h1>🎲 Sorteos desde CSV</h1>

    <section class="card">
      <div class="row">
        <label for="column">Columna</label>
        <select id="column"></select>
      </div>

      <div class="row">
        <label for="n">Cantidad de ganadores</label>
        <input id="n" type="number" min="1" value="1">
      </div>

      <div class="row checkbox">
        <label><input id="unique" type="checkbox" checked> Sin repetidos</label>
      </div>

      <div class="row">
        <label for="seed">Semilla (opcional)</label>
        <input id="seed" type="number" placeholder="ej. 42">
      </div>

      <button id="drawBtn">🎟️ Sortear</button>
      <p id="error" class="error" hidden></p>
    </section>

    <section class="card">
      <h2>Ganadores</h2>
      <ol id="winners" class="winners"></ol>
    </section>
  </main>

  <script>
    async function loadColumns() {
      const res = await fetch('/columns');
      const data = await res.json();
      const sel = document.getElementById('column');
      sel.innerHTML = '';
      (data.columns || []).forEach(c => {
        const opt = document.createElement('option');
        opt.value = c; opt.textContent = c;
        sel.appendChild(opt);
      });
    }

    async function draw() {
      const error = document.getElementById('error');
      error.hidden = true; error.textContent = '';

      const column = document.getElementById('column').value;
      const n = parseInt(document.getElementById('n').value || '1', 10);
      const unique = document.getElementById('unique').checked;
      const seedVal = document.getElementById('seed').value;
      const seed = seedVal === '' ? null : Number(seedVal);

      const body = { column, n, unique, seed, dropna: true };
      const res = await fetch('/draw', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
      });

      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        error.textContent = (data && data.detail) ? data.detail : 'Error en el sorteo';
        error.hidden = false;
        return;
      }

      const data = await res.json();
      const list = document.getElementById('winners');
      list.innerHTML = '';
      (data.winners || []).forEach(w => {
        const li = document.createElement('li');
        li.textContent = w;
        list.appendChild(li);
      });
    }

    document.getElementById('drawBtn').addEventListener('click', draw);
    loadColumns();
  </script>
</body>
</html>
    """

# --- CLI (opcional para local) ---
@cli.command()
def draw_cli(
    column: str,
    n: int = 1,
    unique: bool = True,
    seed: Optional[int] = None,
):
    winners = raffle.draw(column=column, n=n, unique=unique, seed=seed)
    typer.echo("\n".join(winners))

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "api":
        uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
    else:
        cli()
