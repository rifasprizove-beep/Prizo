from __future__ import annotations
import random
from typing import List, Optional, Sequence
import pandas as pd

class Raffle:
    def __init__(self, df: pd.DataFrame):
        self.df = df

    @classmethod
    def from_csv(cls, path: str, sep: str = ",", encoding: str = "utf-8") -> "Raffle":
        df = pd.read_csv(path, sep=sep, encoding=encoding)
        return cls(df)

    def draw(
        self,
        column: str,
        n: int = 1,
        unique: bool = True,
        seed: Optional[int] = None,
        include: Optional[Sequence[str]] = None,
        exclude: Optional[Sequence[str]] = None,
        dropna: bool = True,
    ) -> List[str]:
        """
        Devuelve n valores aleatorios de la columna.

        - unique=True: no repetir ganadores
        - seed: reproducibilidad
        - include/exclude: filtran por valor exacto en la columna
        - dropna: excluye celdas vacías/NaN
        """
        if column not in self.df.columns:
            raise ValueError(f"Columna no encontrada: {column}")

        series = self.df[column]
        if dropna:
            series = series.dropna()
        values = series.astype(str).tolist()

        # Filtros
        if include:
            include_set = set(include)
            values = [v for v in values if v in include_set]
        if exclude:
            exclude_set = set(exclude)
            values = [v for v in values if v not in exclude_set]

        if not values:
            raise ValueError("No hay valores elegibles después de filtrar.")

        rng = random.Random(seed)
        if unique:
            if n > len(set(values)):
                raise ValueError("n > valores únicos disponibles.")
            uniques = list(set(values))
            rng.shuffle(uniques)
            return uniques[:n]
        else:
            return [rng.choice(values) for _ in range(n)]
