#!/usr/bin/env python3
"""Runner mínimo para el 'bombo' que selecciona ganadores desde un CSV.

Ejemplo:
  python run_bombo.py --csv sample.csv --n 3 --seed 42 --unique

"""
from bombo import load_participants_from_csv, pick_winners
import argparse

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--csv", default="sample.csv", help="Ruta al CSV de participantes")
    parser.add_argument("--n", type=int, default=1, help="Número de ganadores")
    parser.add_argument("--seed", type=int, default=None, help="Semilla opcional")
    parser.add_argument("--unique", action="store_true", help="Forzar ganadores únicos")
    args = parser.parse_args()

    participants = load_participants_from_csv(args.csv)
    if not participants:
        print("No hay participantes en el CSV.")
        return

    winners = pick_winners(participants, n=args.n, unique=args.unique, seed=args.seed)
    print("Ganadores:")
    for w in winners:
        print(f"{w['position']}. {w['nombre']} <{w['email_masked']}> (ticket {w['draw_ticket']})")

if __name__ == '__main__':
    main()
