"""DAG Airflow : pipeline quotidien AeroOps Intelligence.

ingestion vols -> ingestion météo -> features -> (ré)entraînement hebdo -> scoring -> contrôle qualité

En production, `ingest_flights` lirait le flux de la compagnie (ou BTS/OpenSky),
et `score` tournerait plusieurs fois par jour pour le modèle tactique.
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta

from airflow import DAG
from airflow.operators.python import BranchPythonOperator, PythonOperator
from airflow.operators.empty import EmptyOperator

SOURCE = os.getenv("AEROOPS_SOURCE", "synthetic")  # synthetic | bts

default_args = {"owner": "aeroops", "retries": 2, "retry_delay": timedelta(minutes=5)}


def _ingest_flights(**ctx):
    from aeroops import pipeline
    if SOURCE == "bts":
        d = ctx["logical_date"] - timedelta(days=45)  # BTS publie avec ~1 mois de décalage
        return pipeline.ingest_bts(d.year, d.month, os.getenv("AEROOPS_CARRIERS", "B6").split(","), with_weather=False)
    return pipeline.ingest_synthetic()


def _ingest_weather(**ctx):
    if SOURCE != "bts":
        return "météo générée avec les vols"
    from aeroops.data import metar
    from aeroops.db import read_sql, replace_rows
    import pandas as pd
    aps = read_sql("SELECT a.* FROM airports a JOIN (SELECT origin, COUNT(*) n FROM flights GROUP BY origin "
                   "ORDER BY n DESC LIMIT 30) t ON t.origin = a.iata")
    span = read_sql("SELECT MIN(sched_dep) s, MAX(sched_arr) e FROM flights")
    w = metar.fetch_airports(aps, pd.Timestamp(span.s[0]), pd.Timestamp(span.e[0]), us=True)
    return replace_rows(w, "weather_hourly")


def _features(**_):
    from aeroops import pipeline
    return pipeline.build_features()


def _should_retrain(**ctx):
    # ré-entraînement chaque lundi, ou si aucun modèle n'existe
    from aeroops.config import MODELS_DIR
    if ctx["logical_date"].weekday() == 0 or not (MODELS_DIR / "meta.json").exists():
        return "train"
    return "skip_train"


def _train(**_):
    from aeroops import pipeline
    report = pipeline.train()
    mae = report["models"]["tactical"]["metrics"]["mae_min"]
    baseline = report["baselines"]["regle_propagation_simple"]["mae_min"]
    if mae >= baseline:
        raise ValueError(f"Modèle tactique ({mae}) moins bon que la règle simple ({baseline}) : déploiement bloqué")
    return report["models"]["tactical"]["metrics"]


def _score(**_):
    from aeroops import pipeline
    return pipeline.score(last_days=14)


def _quality_check(**_):
    from aeroops.db import read_sql
    n = read_sql("SELECT COUNT(*) n FROM predictions").n[0]
    nulls = read_sql("SELECT COUNT(*) n FROM flights WHERE dep_delay IS NULL AND cancelled = 0").n[0]
    if n == 0:
        raise ValueError("Aucune prédiction produite")
    return {"predictions": int(n), "flights_without_delay": int(nulls)}


with DAG(
    dag_id="aeroops_daily_pipeline",
    description="Prédiction des retards et KPI opérationnels",
    start_date=datetime(2026, 9, 1),
    schedule="0 4 * * *",          # 04:00 UTC, avant la première vague de départs
    catchup=False,
    default_args=default_args,
    tags=["aeroops", "ml", "ops"],
) as dag:
    ingest_flights = PythonOperator(task_id="ingest_flights", python_callable=_ingest_flights)
    ingest_weather = PythonOperator(task_id="ingest_weather", python_callable=_ingest_weather)
    features = PythonOperator(task_id="build_features", python_callable=_features)
    branch = BranchPythonOperator(task_id="should_retrain", python_callable=_should_retrain)
    train = PythonOperator(task_id="train", python_callable=_train)
    skip = EmptyOperator(task_id="skip_train")
    score = PythonOperator(task_id="score", python_callable=_score, trigger_rule="none_failed_min_one_success")
    qc = PythonOperator(task_id="quality_check", python_callable=_quality_check)

    ingest_flights >> ingest_weather >> features >> branch >> [train, skip] >> score >> qc
