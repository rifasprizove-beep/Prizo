import pandas as pd
from logic import Raffle

def test_draw_unique():
    df = pd.DataFrame({"nombre": ["Ana", "Luis", "Sara"]})
    r = Raffle(df)
    winners = r.draw("nombre", n=2, unique=True, seed=42)
    assert len(winners) == 2
    assert len(set(winners)) == 2

def test_draw_non_unique():
    df = pd.DataFrame({"nombre": ["Ana", "Ana", "Luis"]})
    r = Raffle(df)
    winners = r.draw("nombre", n=5, unique=False, seed=1)
    assert len(winners) == 5
