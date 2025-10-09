# app.py (fragmentos relevantes)
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional
import uvicorn
import typer

from logic import Raffle
from settings import settings

app = FastAPI(title="Sorteos CSV", version="1.0.0")
cli = typer.Typer(add_completion=False)

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
    return {"columns": raffle.columns}   # <-- ya no usamos df.columns

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
