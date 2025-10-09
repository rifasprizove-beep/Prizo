# tests/test_logic.py
from logic import Raffle

def test_draw_unique():
    rows = [{"nombre": "Ana"}, {"nombre": "Luis"}, {"nombre": "Sara"}]
    r = Raffle(rows=rows, columns=["nombre"])
    winners = r.draw("nombre", n=2, unique=True, seed=42)
    assert len(winners) == 2
    assert len(set(winners)) == 2

def test_draw_non_unique():
    rows = [{"nombre": "Ana"}, {"nombre": "Ana"}, {"nombre": "Luis"}]
    r = Raffle(rows=rows, columns=["nombre"])
    winners = r.draw("nombre", n=5, unique=False, seed=1)
    assert len(winners) == 5
