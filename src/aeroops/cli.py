"""Ligne de commande : python -m aeroops.cli <commande>."""
from __future__ import annotations

import argparse
import json

from . import pipeline


def main() -> None:
    p = argparse.ArgumentParser(prog="aeroops", description="AeroOps Intelligence - pipeline")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("demo", help="Données de démo + features + entraînement + scoring")
    g = sub.add_parser("ingest-synthetic"); g.add_argument("--start", default="2026-05-01"); g.add_argument("--end", default="2026-08-31")
    b = sub.add_parser("ingest-bts", help="Données réelles BTS + METAR")
    b.add_argument("--year", type=int, required=True); b.add_argument("--month", type=int, required=True)
    b.add_argument("--carriers", nargs="+", default=["B6"], help="Codes IATA compagnies (ex. B6 AA DL)")
    b.add_argument("--no-weather", action="store_true")
    sub.add_parser("features"); sub.add_parser("train")
    s = sub.add_parser("score"); s.add_argument("--days", type=int, default=14)
    a = p.parse_args()

    if a.cmd == "demo":
        res = pipeline.run_all()
    elif a.cmd == "ingest-synthetic":
        res = pipeline.ingest_synthetic(a.start, a.end)
    elif a.cmd == "ingest-bts":
        res = pipeline.ingest_bts(a.year, a.month, a.carriers, with_weather=not a.no_weather)
    elif a.cmd == "features":
        res = pipeline.build_features()
    elif a.cmd == "train":
        r = pipeline.train()
        res = {"baselines": r["baselines"], **{k: v["metrics"] for k, v in r["models"].items()}}
    else:
        res = pipeline.score(a.days)
    print(json.dumps(res, indent=2, ensure_ascii=False, default=str))


if __name__ == "__main__":
    main()
