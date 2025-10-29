from __future__ import annotations
import csv
import random
import uuid
from typing import List, Dict, Optional


def _mask_email(email: str) -> str:
    if not email or "@" not in email:
        return email
    user, dom = email.split("@", 1)
    def mask(s: str) -> str:
        if len(s) <= 2:
            return s[:1] + "*"
        return s[:2] + "***"
    dom_parts = dom.split(".")
    dom_parts[0] = mask(dom_parts[0])
    return f"{mask(user)}@{'.'.join(dom_parts)}"


def pick_winners(participants: List[Dict[str, str]], n: int = 1, unique: bool = True, seed: Optional[int] = None) -> List[Dict[str, str]]:
    """Selecciona `n` ganadores de la lista de participantes.

    participants: lista de dicts que al menos contienen 'nombre' y 'email'
    n: número de ganadores a elegir
    unique: si True no repite ganadores (sample), si False puede repetirse
    seed: semilla para reproducibilidad

    Devuelve una lista de dicts con keys: position, nombre, email, email_masked, draw_ticket (uuid)
    """
    if not participants:
        return []
    if n < 1:
        return []

    rng = random.Random(seed)
    pool = list(participants)

    chosen = []
    if unique:
        if n >= len(pool):
            chosen = pool
        else:
            chosen = rng.sample(pool, n)
    else:
        for _ in range(n):
            chosen.append(rng.choice(pool))

    winners = []
    for i, p in enumerate(chosen):
        winners.append({
            "position": i + 1,
            "nombre": p.get("nombre") or p.get("name"),
            "email": p.get("email"),
            "email_masked": _mask_email(p.get("email") or ""),
            "draw_ticket": str(uuid.uuid4()),
        })
    return winners


def load_participants_from_csv(path: str, encoding: str = "utf-8", sep: str = ",") -> List[Dict[str, str]]:
    parts = []
    with open(path, encoding=encoding, newline="") as f:
        reader = csv.DictReader(f, delimiter=sep)
        for row in reader:
            # normalize keys to lower-case
            normalized = {k.strip().lower(): v.strip() for k, v in row.items() if k}
            parts.append(normalized)
    return parts


if __name__ == "__main__":
    # Uso rápido para debug
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", default="sample.csv", help="Ruta al CSV de participantes")
    parser.add_argument("--n", type=int, default=1, help="Número de ganadores")
    parser.add_argument("--seed", type=int, default=None, help="Semilla opcional")
    parser.add_argument("--unique", action="store_true", help="Forzar ganadores únicos")
    args = parser.parse_args()
    participants = load_participants_from_csv(args.csv)
    winners = pick_winners(participants, n=args.n, unique=args.unique, seed=args.seed)
    for w in winners:
        print(f"{w['position']}: {w['nombre']} <{w['email_masked']}> (ticket: {w['draw_ticket']})")
