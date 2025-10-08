from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional
import uvicorn
import typer

from logic import Raffle
from settings import settings

app = FastAPI(title="Sorteos CSV", version="1.0.0")
cli = typer.Typer(add_completion=False)

# Cargar al iniciar
raffle = Raffle.from_csv(settings.CSV_PATH, sep=settings.CSV_SEP, encoding=settings.CSV_ENCODING)

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

@app.get("/health")
async def health():
    return {"status": "ok"}

@app.get("/columns")
async def columns():
    return {"columns": list(raffle.df.columns)}

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

# --- CLI ---
@cli.command()
def draw_cli(
    column: str = typer.Option(..., help="Columna del CSV"),
    n: int = typer.Option(1, help="Cantidad de ganadores"),
    unique: bool = typer.Option(True, help="Sin repetidos"),
    seed: Optional[int] = typer.Option(None, help="Semilla para reproducibilidad"),
):
    winners = raffle.draw(column=column, n=n, unique=unique, seed=seed)
    typer.echo("\n".join(winners))

@cli.command(name="list-columns")
def list_columns():
    from rich import print
    print({"columns": list(raffle.df.columns)})

if __name__ == "__main__":
    # Ejecutar como API: python app.py api
    # Ejecutar CLI: python app.py draw-cli --column nombre
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "api":
        uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
    else:
        cli()
