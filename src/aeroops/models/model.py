"""Entraînement, évaluation et explication des modèles XGBoost.

Deux modèles par horizon :
* un régresseur -> retard au départ attendu (minutes) ;
* un classifieur -> probabilité d'un retard >= 15 min (indicateur OTP15).
Les explications utilisent les valeurs SHAP natives de XGBoost
(pred_contribs) agrégées par grande famille de causes.
"""
from __future__ import annotations

import json
from datetime import datetime
from functools import lru_cache

import numpy as np
import pandas as pd
import xgboost as xgb
from sklearn.metrics import (average_precision_score, brier_score_loss, f1_score, mean_absolute_error,
                             precision_score, r2_score, recall_score, roc_auc_score, root_mean_squared_error)

from ..config import MODEL, MODELS_DIR, OPS
from ..features.build import CATEGORICAL, FEATURE_TO_GROUP, STRATEGIC_FEATURES, TACTICAL_FEATURES

FEATURE_SETS = {"strategic": STRATEGIC_FEATURES, "tactical": TACTICAL_FEATURES}
TARGET_CLIP = (-15, 300)


def temporal_split(df: pd.DataFrame, test_days: int = MODEL.test_days):
    dates = pd.to_datetime(df["flight_date"])
    test_start = dates.max() - pd.Timedelta(days=test_days - 1)
    valid_start = test_start - pd.Timedelta(days=test_days)
    train = df[dates < valid_start]
    valid = df[(dates >= valid_start) & (dates < test_start)]
    test = df[dates >= test_start]
    return train, valid, test


def _X(df: pd.DataFrame, features: list[str], categories: dict | None = None) -> pd.DataFrame:
    X = df[features].copy()
    for c in CATEGORICAL:
        if c in X:
            cats = (categories or {}).get(c)
            X[c] = pd.Categorical(X[c].astype(str), categories=cats) if cats else X[c].astype("category")
    return X


def _metrics(y_min: np.ndarray, pred_min: np.ndarray, y_cls: np.ndarray, prob: np.ndarray) -> dict:
    out = {
        "mae_min": mean_absolute_error(y_min, pred_min),
        "rmse_min": root_mean_squared_error(y_min, pred_min),
        "r2": r2_score(y_min, pred_min),
    }
    if prob is not None:
        pred_cls = (prob >= 0.5).astype(int)
        out.update({
            "roc_auc": roc_auc_score(y_cls, prob),
            "pr_auc": average_precision_score(y_cls, prob),
            "brier": brier_score_loss(y_cls, prob),
            "precision@0.5": precision_score(y_cls, pred_cls, zero_division=0),
            "recall@0.5": recall_score(y_cls, pred_cls, zero_division=0),
            "f1@0.5": f1_score(y_cls, pred_cls, zero_division=0),
        })
    return {k: round(float(v), 4) for k, v in out.items()}


def train_all(features_df: pd.DataFrame) -> dict:
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    df = features_df.dropna(subset=["dep_delay"])
    train, valid, test = temporal_split(df)
    categories = {c: sorted(df[c].astype(str).unique().tolist()) for c in CATEGORICAL}
    report = {"trained_at": datetime.now().isoformat(timespec="seconds"),
              "n_train": len(train), "n_valid": len(valid), "n_test": len(test),
              "test_period": [str(test["flight_date"].min()), str(test["flight_date"].max())],
              "delay15_rate_test": round(float((test["dep_delay"] >= OPS.otp_threshold_min).mean()), 4),
              "models": {}}

    y = {k: d["dep_delay"].clip(*TARGET_CLIP).values for k, d in (("train", train), ("valid", valid), ("test", test))}
    yc = {k: (d["dep_delay"] >= OPS.otp_threshold_min).astype(int).values
          for k, d in (("train", train), ("valid", valid), ("test", test))}

    # Baselines : sans elles, une métrique ML ne veut rien dire.
    hist = test["route_mean_arr_delay_28d"].fillna(train["dep_delay"].mean()).values
    rule = np.maximum(hist, test["inbound_reactionary_est"].fillna(0).values)
    report["baselines"] = {
        "moyenne_globale": _metrics(y["test"], np.full(len(test), y["train"].mean()), yc["test"], None),
        "historique_ligne_28j": _metrics(y["test"], hist, yc["test"], None),
        "regle_propagation_simple": _metrics(y["test"], rule, yc["test"], None),
    }

    for name, feats in FEATURE_SETS.items():
        Xtr, Xva, Xte = (_X(d, feats, categories) for d in (train, valid, test))
        reg = xgb.XGBRegressor(**MODEL.xgb, objective="reg:squarederror", enable_categorical=True,
                               early_stopping_rounds=100, random_state=MODEL.random_state, eval_metric="mae")
        reg.fit(Xtr, y["train"], eval_set=[(Xva, y["valid"])], verbose=False)
        # Pas de rééquilibrage des classes : on veut des probabilités calibrées,
        # car elles alimentent un calcul de coût (espérance), pas seulement un tri.
        clf = xgb.XGBClassifier(**MODEL.xgb, objective="binary:logistic", enable_categorical=True,
                                early_stopping_rounds=100, random_state=MODEL.random_state, eval_metric="logloss")
        clf.fit(Xtr, yc["train"], eval_set=[(Xva, yc["valid"])], verbose=False)

        pred = reg.predict(Xte)
        prob = clf.predict_proba(Xte)[:, 1]
        metrics = _metrics(y["test"], pred, yc["test"], prob)

        contrib = reg.get_booster().predict(xgb.DMatrix(Xte, enable_categorical=True), pred_contribs=True,
                                            iteration_range=(0, reg.best_iteration + 1))[:, :-1]
        imp = pd.Series(np.abs(contrib).mean(0), index=feats)
        group_imp = imp.groupby(imp.index.map(FEATURE_TO_GROUP)).sum().sort_values(ascending=False)

        reg.save_model(MODELS_DIR / f"{name}_reg.json")
        clf.save_model(MODELS_DIR / f"{name}_clf.json")
        report["models"][name] = {
            "features": feats, "best_iteration_reg": int(reg.best_iteration),
            "metrics": metrics,
            "shap_by_factor_min": group_imp.round(2).to_dict(),
            "top_features": imp.sort_values(ascending=False).head(12).round(2).to_dict(),
        }
    (MODELS_DIR / "meta.json").write_text(json.dumps({"categories": categories}, indent=2), encoding="utf-8")
    (MODELS_DIR / "report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    load_models.cache_clear()
    return report


# --------------------------------------------------------------------------- inférence
@lru_cache(maxsize=1)
def load_models() -> dict:
    meta = json.loads((MODELS_DIR / "meta.json").read_text(encoding="utf-8"))
    models = {"categories": meta["categories"]}
    for name in FEATURE_SETS:
        reg, clf = xgb.XGBRegressor(), xgb.XGBClassifier()
        reg.load_model(MODELS_DIR / f"{name}_reg.json")
        clf.load_model(MODELS_DIR / f"{name}_clf.json")
        models[name] = (reg, clf)
    return models


def predict(df: pd.DataFrame, model_name: str = "tactical", explain: bool = True) -> pd.DataFrame:
    models = load_models()
    reg, clf = models[model_name]
    feats = FEATURE_SETS[model_name]
    X = _X(df, feats, models["categories"])
    out = pd.DataFrame({"flight_id": df["flight_id"].values,
                        "pred_delay_min": reg.predict(X).round(1),
                        "prob_delay15": clf.predict_proba(X)[:, 1].round(4)})
    if explain:
        contrib = reg.get_booster().predict(xgb.DMatrix(X, enable_categorical=True), pred_contribs=True,
                                            iteration_range=(0, reg.best_iteration + 1))
        groups = pd.DataFrame(contrib[:, :-1], columns=feats).T.groupby(lambda f: FEATURE_TO_GROUP[f]).sum().T
        out["top_factor"] = groups.idxmax(axis=1).values
        out["_contrib"] = list(groups.round(1).to_dict(orient="records"))
        out["_base"] = contrib[:, -1].round(1)
    return out


def explain_flight(df_row: pd.DataFrame, model_name: str = "tactical") -> dict:
    """Décomposition du retard prédit d'un vol : base + contribution de chaque famille de causes."""
    p = predict(df_row, model_name).iloc[0]
    factors = sorted(({"factor": k, "minutes": float(v)} for k, v in p["_contrib"].items()),
                     key=lambda x: -abs(x["minutes"]))
    row = df_row.iloc[0]
    evidence = {k: (None if pd.isna(row.get(k)) else (row.get(k).item() if hasattr(row.get(k), "item") else row.get(k)))
                for k in ["prev_leg_dep_delay", "turn_slack_min", "o_sev", "d_sev", "o_thunderstorm",
                          "d_thunderstorm", "o_visibility_km", "o_gust_kt", "o_sched_deps_hour",
                          "route_mean_arr_delay_28d"] if k in row}
    return {"flight_id": p["flight_id"], "model": model_name, "pred_delay_min": float(p["pred_delay_min"]),
            "prob_delay15": float(p["prob_delay15"]), "base_min": float(p["_base"]), "factors": factors,
            "evidence": evidence}
