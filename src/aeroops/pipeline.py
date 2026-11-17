"""Étapes du pipeline, appelées par la CLI et par le DAG Airflow."""
from __future__ import annotations

from datetime import datetime

import pandas as pd

from .config import DATA_DIR
from .db import get_engine, init_db, read_sql, replace_rows

FEATURES_PATH = DATA_DIR / "features.parquet"
TABLE_ORDER = ["airports", "aircraft", "flights", "weather_hourly"]


def ingest_synthetic(start: str = "2026-05-01", end: str = "2026-08-31", seed: int = 7) -> dict:
    from .data.synthetic import generate
    init_db()
    data = generate(start, end, seed)
    counts = {t: replace_rows(data[t], t) for t in TABLE_ORDER}
    data["_meta"].to_csv(DATA_DIR / "atc_strike_days.csv", index=False)
    return counts


def ingest_bts(year: int, month: int, carriers: list[str], with_weather: bool = True) -> dict:
    """Données réelles : BTS (vols US) + METAR IEM (météo) pour les aéroports concernés."""
    from .data import bts, metar
    init_db()
    raw = bts.download_month(year, month)
    ref = bts.load_reference_airports(set(raw["Origin"]) | set(raw["Dest"]))
    data = bts.to_schema(raw, ref, carriers=carriers)
    counts = {t: replace_rows(data[t], t) for t in ["airports", "aircraft", "flights"]}
    if with_weather:
        f = data["flights"]
        busiest = f["origin"].value_counts().head(30).index
        aps = data["airports"][data["airports"]["iata"].isin(busiest)]
        w = metar.fetch_airports(aps, f["sched_dep"].min().normalize(), f["sched_arr"].max().normalize(), us=True)
        counts["weather_hourly"] = replace_rows(w, "weather_hourly")
    return counts


def build_features() -> int:
    from .features.build import build_features as _build
    flights = read_sql("SELECT * FROM flights", parse_dates=["sched_dep", "sched_arr"])
    weather = read_sql("SELECT * FROM weather_hourly", parse_dates=["ts"])
    feats = _build(flights, weather)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    feats.to_parquet(FEATURES_PATH, index=False)
    return len(feats)


def load_features() -> pd.DataFrame:
    from .features.build import CATEGORICAL
    df = pd.read_parquet(FEATURES_PATH)
    df["flight_date"] = pd.to_datetime(df["flight_date"]).dt.date
    for c in CATEGORICAL:
        df[c] = df[c].astype(str)
    return df


def train() -> dict:
    from .models.model import train_all
    return train_all(load_features())


def score(last_days: int = 14) -> int:
    """Score les derniers jours (période d'exploitation affichée dans le dashboard)."""
    from .models.model import predict
    feats = load_features()
    dates = pd.to_datetime(feats["flight_date"])
    scope = feats[dates > dates.max() - pd.Timedelta(days=last_days)]
    frames = []
    for name in ("tactical", "strategic"):
        p = predict(scope, name)
        frames.append(p[["flight_id", "pred_delay_min", "prob_delay15", "top_factor"]]
                      .assign(model_name=name, scored_at=datetime.now()))
    preds = pd.concat(frames, ignore_index=True)
    return replace_rows(preds, "predictions")


def run_all(source: str = "synthetic") -> dict:
    out = {"ingest": ingest_synthetic() if source == "synthetic" else None}
    out["features"] = build_features()
    report = train()
    out["metrics"] = {k: v["metrics"] for k, v in report["models"].items()}
    out["scored"] = score()
    get_engine.cache_clear()
    return out
