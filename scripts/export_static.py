"""Export de la démo en site statique (Hugging Face Space "static", gratuit).

Toutes les réponses de l'API nécessaires au front sont pré-calculées en JSON.
Seule la simulation de scénarios reste dynamique : elle est recalculée dans le
navigateur par frontend/src/sim/simulation.js, à partir des données exportées
dans sim/<date>.json (port fidèle de src/aeroops/ops/simulation.py).

Usage :
    python -m aeroops.cli demo
    python scripts/export_static.py frontend/public/data [--reference sim_reference.json]

--reference écrit aussi des simulations calculées en Python, utilisées par
frontend/src/sim/simulation.test.mjs pour vérifier que le port JS est exact.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from aeroops.api.main import app  # noqa: E402
from aeroops.db import read_sql  # noqa: E402
from aeroops.models.model import predict  # noqa: E402
from aeroops.ops.simulation import DisruptionSimulator  # noqa: E402
from aeroops.pipeline import load_features  # noqa: E402

MODELS = ("tactical", "strategic")
EVIDENCE = ["prev_leg_dep_delay", "turn_slack_min", "o_sev", "d_sev", "o_thunderstorm", "d_thunderstorm",
            "o_visibility_km", "o_gust_kt", "o_sched_deps_hour", "route_mean_arr_delay_28d"]


def _clean(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    return v.item() if hasattr(v, "item") else v


def write(out: Path, rel: str, payload) -> None:
    path = out / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")


def explanations(feats: pd.DataFrame, model: str) -> dict:
    """Même contenu que GET /api/flights/{id}/explain, calculé en lot pour une journée."""
    p = predict(feats, model)
    out = {}
    for (_, row), (_, pr) in zip(feats.iterrows(), p.iterrows()):
        factors = sorted(({"factor": k, "minutes": float(v)} for k, v in pr["_contrib"].items()),
                         key=lambda x: -abs(x["minutes"]))
        out[pr["flight_id"]] = {
            "flight_id": pr["flight_id"], "model": model,
            "pred_delay_min": float(pr["pred_delay_min"]), "prob_delay15": float(pr["prob_delay15"]),
            "base_min": float(pr["_base"]), "factors": factors,
            "evidence": {k: _clean(row.get(k)) for k in EVIDENCE},
            "actual_dep_delay": float(row["dep_delay"]),
            "flight": {k: str(row[k]) for k in ["flight_number", "tail_number", "origin", "dest", "sched_dep"]},
        }
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("out", type=Path)
    ap.add_argument("--reference", type=Path, help="fichier JSON de simulations Python de référence")
    a = ap.parse_args()
    out: Path = a.out
    c = TestClient(app)

    meta = c.get("/api/meta").json()
    write(out, "meta.json", meta)
    write(out, "model/report.json", c.get("/api/model/report").json())

    # KPI : uniquement les 3 périodes proposées par le dashboard en mode statique
    end = date.fromisoformat(meta["end"])
    starts = {meta["scored_dates"][0], (end - timedelta(days=29)).isoformat(), meta["start"]}
    for s in starts:
        write(out, f"kpis/{s}_{meta['end']}.json", c.get("/api/kpis", params={"start": s, "end": meta["end"]}).json())

    feats = load_features()
    aircraft = read_sql("SELECT * FROM aircraft").to_dict(orient="records")
    reference = []
    for d in meta["scored_dates"]:
        for m in MODELS:
            write(out, f"flights/{d}_{m}.json", c.get("/api/flights", params={"date": d, "model": m}).json())
            day_feats = feats[feats["flight_date"].astype(str) == d]
            write(out, f"explain/{d}_{m}.json", explanations(day_feats, m))
        write(out, f"rotations/{d}.json", c.get("/api/rotations", params={"date": d}).json())

        day = read_sql("SELECT flight_id, flight_number, tail_number, origin, dest, sched_dep, sched_arr, "
                       "distance_km, seats FROM flights WHERE flight_date = :d AND cancelled = 0", {"d": d},
                       parse_dates=["sched_dep", "sched_arr"])
        legs = day.assign(sched_dep=day["sched_dep"].dt.strftime("%Y-%m-%dT%H:%M"),
                          sched_arr=day["sched_arr"].dt.strftime("%Y-%m-%dT%H:%M")).to_dict(orient="records")
        write(out, f"sim/{d}.json", {"legs": legs, "aircraft": aircraft})

        if a.reference:
            sim = DisruptionSimulator(day, pd.DataFrame(aircraft))
            for fid in day.sort_values("sched_dep")["flight_id"].iloc[::25]:
                for delay in (20, 60, 150, 300):
                    reference.append(sim.simulate(fid, delay))

    if a.reference:
        a.reference.parent.mkdir(parents=True, exist_ok=True)
        a.reference.write_text(json.dumps(reference, ensure_ascii=False), encoding="utf-8")
    size = sum(f.stat().st_size for f in out.rglob("*.json")) / 1e6
    print(f"Export statique : {sum(1 for _ in out.rglob('*.json'))} fichiers, {size:.1f} Mo -> {out}")


if __name__ == "__main__":
    main()
