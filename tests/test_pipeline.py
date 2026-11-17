import pandas as pd
from fastapi.testclient import TestClient


def test_history_features_exclude_current_day(pipeline_ready):
    """Anti-fuite : l'historique d'un jour J ne doit dépendre que des jours < J."""
    from aeroops.pipeline import load_features
    f = load_features()
    first_day = f["flight_date"].min()
    assert f.loc[f["flight_date"] == first_day, "route_mean_arr_delay_28d"].isna().all()


def test_tactical_beats_baselines(pipeline_ready):
    r = pipeline_ready
    tac = r["models"]["tactical"]["metrics"]["mae_min"]
    assert tac < r["baselines"]["historique_ligne_28j"]["mae_min"]
    assert tac < r["baselines"]["regle_propagation_simple"]["mae_min"]
    assert r["models"]["tactical"]["metrics"]["roc_auc"] > 0.75


def test_api_end_to_end(pipeline_ready):
    from aeroops.api.main import app
    c = TestClient(app)
    meta = c.get("/api/meta").json()
    day = meta["scored_dates"][-1]
    k = c.get("/api/kpis", params={"start": meta["scored_dates"][0], "end": day}).json()
    assert 0 < k["kpi_global"]["otp15"] < 1
    flights = c.get("/api/flights", params={"date": day}).json()
    assert flights and flights[0]["prob_delay15"] is not None
    fid = flights[0]["flight_id"]
    exp = c.get(f"/api/flights/{fid}/explain").json()
    assert abs(exp["base_min"] + sum(x["minutes"] for x in exp["factors"]) - exp["pred_delay_min"]) < 1.0
    sim = c.post("/api/simulate", json={"flight_id": fid, "delay_min": 120}).json()
    keys = {s["key"] for s in sim["scenarios"]}
    assert {"no_action", "quick_turn", "spare", "swap", "cancel_rt"} <= keys
    best = next(s for s in sim["scenarios"] if s["key"] == sim["recommended"])
    assert all(best["total_cost"] <= s["total_cost"] for s in sim["scenarios"] if s["feasible"])
