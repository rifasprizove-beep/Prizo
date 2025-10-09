# logic.py
from __future__ import annotations
import csv
import random
from typing import List, Optional, Sequence

class Raffle:
    def __init__(self, rows: List[dict], columns: List[str]):
        self.rows = rows
        self._columns = columns

    @classmethod
    def from_csv(cls, path: str, sep: str = ",", encoding: str = "utf-8") -> "Raffle":
        with open(path, "r", encoding=encoding, newline="") as f:
            reader = csv.DictReader(f, delimiter=sep)
            rows = list(reader)
            columns = reader.fieldnames or []
        return cls(rows=rows, columns=columns)

    @property
    def columns(self) -> List[str]:
        return list(self._columns)

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
        if column not in self._columns:
            raise ValueError(f"Columna no encontrada: {column}")

        # Extrae valores de la columna
        values: List[str] = []
        for row in self.rows:
            val = row.get(column, "")
            if dropna and (val is None or str(val).strip() == ""):
                continue
            values.append(str(val))

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
            uniques = list(set(values))
            if n > len(uniques):
                raise ValueError("n > valores únicos disponibles.")
            rng.shuffle(uniques)
            return uniques[:n]
        else:
            return [rng.choice(values) for _ in range(n)]
