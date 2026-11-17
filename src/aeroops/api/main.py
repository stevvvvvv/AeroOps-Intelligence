"""API REST AeroOps Intelligence (FastAPI).

Lancement : uvicorn aeroops.api.main:app --reload
Documentation interactive : http://localhost:8000/docs
"""
from __future__ import annotations

import json
from datetime import date
from functools import lru_cache
from typing import Optional

import numpy as np
import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from ..config import DATA_DIR, MODELS_DIR, OPS, ROOT
from ..db import load_named_queries, read_sql
from ..models.model import explain_flight
from ..ops.simulation import DisruptionSimulator
from ..pipeline import load_features

app = FastAPI(title="AeroOps Intelligence API", version="1.0.0",
              description="Prédiction des retards, retards en cascade et simulation de scénarios OCC.")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])
QUERIES = load_named_queries()


def _records(df: pd.DataFrame) -> list[dict]:
    df = df.copy()
    for c in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[c]):
            df[c] = df[c].dt.strftime("%Y-%m-%dT%H:%M")
    return json.loads(df.replace({np.nan: None}).to_json(orient="records", date_format="iso"))


@lru_cache(maxsize=1)
def _features() -> pd.DataFrame:
    return load_features().set_index("flight_id", drop=False)


def _day_flights(d: date) -> pd.DataFrame:
    df = read_sql("SELECT * FROM flights WHERE flight_date = :d AND cancelled = 0", {"d": d},
                  parse_dates=["sched_dep", "sched_arr", "actual_dep", "actual_arr"])
    if df.empty:
        raise HTTPException(404, f"Aucun vol le {d}")
    return df


# ------------------------------------------------------------------ référentiel
@app.get("/api/health")
def health():
    return {"status": "ok", "models": (MODELS_DIR / "meta.json").exists(), "features": (DATA_DIR / "features.parquet").exists()}


@app.get("/api/meta")
def meta():
    rng = read_sql("SELECT MIN(flight_date) AS start_date, MAX(flight_date) AS end_date, COUNT(*) AS flights FROM flights").iloc[0]
    scored = read_sql("""SELECT DISTINCT f.flight_date FROM predictions p JOIN flights f ON f.flight_id = p.flight_id
                         ORDER BY f.flight_date""")
    airports = read_sql("SELECT iata, name, lat, lon, is_hub FROM airports ORDER BY iata")
    strikes = DATA_DIR / "atc_strike_days.csv"
    return {"start": str(rng["start_date"]), "end": str(rng["end_date"]), "flights": int(rng["flights"]),
            "scored_dates": [str(d) for d in scored["flight_date"]],
            "airports": _records(airports),
            "atc_strike_days": pd.read_csv(strikes)["strike_day"].tolist() if strikes.exists() else [],
            "ops_params": OPS.__dict__}


# ------------------------------------------------------------------ dashboard
@app.get("/api/kpis")
def kpis(start: date, end: date):
    p = {"start": start, "end": end}
    out = {name: _records(read_sql(q, p)) for name, q in QUERIES.items()}
    out["kpi_global"] = out["kpi_global"][0]
    out["kpi_causes"] = out["kpi_causes"][0]
    hourly = read_sql("SELECT sched_dep, dep_delay, arr_delay FROM flights WHERE flight_date BETWEEN :start AND :end", p,
                      parse_dates=["sched_dep"])
    hourly = hourly.groupby(hourly["sched_dep"].dt.hour).agg(
        flights=("dep_delay", "size"), avg_dep_delay=("dep_delay", "mean"),
        delay15_rate=("dep_delay", lambda s: (s >= OPS.otp_threshold_min).mean())).reset_index(names="hour")
    out["kpi_by_hour"] = _records(hourly.round(3))
    return out


@app.get("/api/model/report")
def model_report():
    path = MODELS_DIR / "report.json"
    if not path.exists():
        raise HTTPException(404, "Modèle non entraîné : lancer `python -m aeroops.cli demo`")
    return json.loads(path.read_text(encoding="utf-8"))


# ------------------------------------------------------------------ vols & prédictions
@app.get("/api/flights")
def flights(day: date = Query(..., alias="date"), model: str = "tactical", airport: Optional[str] = None,
            min_prob: float = 0.0, limit: int = 500):
    q = """SELECT f.flight_id, f.flight_number, f.tail_number, f.origin, f.dest, f.sched_dep, f.sched_arr,
                  f.dep_delay, f.arr_delay, f.seats, f.distance_km,
                  p.pred_delay_min, p.prob_delay15, p.top_factor
           FROM flights f LEFT JOIN predictions p ON p.flight_id = f.flight_id AND p.model_name = :model
           WHERE f.flight_date = :d"""
    params = {"d": day, "model": model}
    if airport:
        q += " AND (f.origin = :ap OR f.dest = :ap)"
        params["ap"] = airport.upper()
    df = read_sql(q, params, parse_dates=["sched_dep", "sched_arr"])
    df = df[df["prob_delay15"].fillna(0) >= min_prob].sort_values("prob_delay15", ascending=False).head(limit)
    return _records(df)


@app.get("/api/flights/{flight_id}/explain")
def explain(flight_id: str, model: str = "tactical"):
    feats = _features()
    if flight_id not in feats.index:
        raise HTTPException(404, "Vol inconnu")
    res = explain_flight(feats.loc[[flight_id]], model)
    row = feats.loc[flight_id]
    res["actual_dep_delay"] = float(row["dep_delay"])
    res["flight"] = {k: str(row[k]) for k in ["flight_number", "tail_number", "origin", "dest", "sched_dep"]}
    return res


# ------------------------------------------------------------------ rotations, cascade, simulation
@app.get("/api/rotations")
def rotations(day: date = Query(..., alias="date"), model: str = "tactical"):
    df = _day_flights(day)
    pr = read_sql("SELECT flight_id, pred_delay_min, prob_delay15 FROM predictions WHERE model_name = :m", {"m": model})
    df = df.merge(pr, on="flight_id", how="left").sort_values(["tail_number", "sched_dep"])
    ac = read_sql("SELECT * FROM aircraft")
    tails = []
    for tail, g in df.groupby("tail_number"):
        a = ac[ac["tail_number"] == tail]
        tails.append({"tail_number": tail, "ac_type": a["ac_type"].iat[0] if len(a) else None,
                      "base": a["base"].iat[0] if len(a) else None,
                      "reactionary_min": float(g["arr_delay"].clip(lower=0).sum()),
                      "legs": _records(g[["flight_id", "flight_number", "origin", "dest", "sched_dep", "sched_arr",
                                          "dep_delay", "arr_delay", "pred_delay_min", "prob_delay15"]])})
    spares = _records(ac[ac["is_spare"] == 1])
    return {"date": str(day), "tails": tails, "spares": spares}


class DisruptionIn(BaseModel):
    flight_id: str
    delay_min: float = Field(45, ge=0, le=720, description="Retard initial au départ (min)")


def _simulator(flight_id: str) -> DisruptionSimulator:
    d = read_sql("SELECT flight_date FROM flights WHERE flight_id = :f", {"f": flight_id})
    if d.empty:
        raise HTTPException(404, "Vol inconnu")
    day = pd.to_datetime(d["flight_date"].iat[0]).date()
    return DisruptionSimulator(_day_flights(day), read_sql("SELECT * FROM aircraft"))


@app.post("/api/cascade")
def cascade(body: DisruptionIn):
    return _simulator(body.flight_id).cascade(body.flight_id, body.delay_min)


@app.post("/api/simulate")
def simulate(body: DisruptionIn):
    return _simulator(body.flight_id).simulate(body.flight_id, body.delay_min)


# Front React compilé servi par l'API (déploiement mono-conteneur)
_dist = ROOT / "frontend" / "dist"
if _dist.exists():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="front")
