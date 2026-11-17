"""Feature engineering pour la prédiction des retards au départ.

Règle d'or : chaque variable doit être CONNUE au moment de la prédiction.
* modèle "strategic" (J-1) : programme, météo prévue, congestion, historique
  des jours précédents ;
* modèle "tactical" (H-2 / temps réel) : + retard du leg entrant, déjà parti.
La météo observée sert de proxy à la prévision (TAF/modèles) : c'est un biais
optimiste assumé et documenté dans le README.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..config import OPS

CATEGORICAL = ["origin", "dest"]

STRATEGIC_FEATURES = [
    "origin", "dest", "dep_hour", "dow", "month", "is_weekend", "distance_km", "sched_block_min",
    "leg_of_day", "turn_slack_min", "is_first_leg",
    "o_wind_kt", "o_gust_kt", "o_visibility_km", "o_precip_mm", "o_ceiling_ft", "o_thunderstorm", "o_sev",
    "o_sev_max3h", "d_wind_kt", "d_gust_kt", "d_visibility_km", "d_precip_mm", "d_ceiling_ft",
    "d_thunderstorm", "d_sev", "d_sev_max3h",
    "o_sched_deps_hour", "d_sched_arrs_hour",
    "route_mean_arr_delay_28d", "flight_delay15_rate_28d", "origin_mean_dep_delay_prev_day",
    "origin_day_sev_sum",
]
TACTICAL_FEATURES = STRATEGIC_FEATURES + ["prev_leg_dep_delay", "inbound_reactionary_est"]

# Regroupement des variables en facteurs lisibles pour un contrôleur des opérations (OCC).
FACTOR_GROUPS = {
    "Retard de l'avion entrant": ["prev_leg_dep_delay", "inbound_reactionary_est"],
    "Marge de rotation": ["turn_slack_min", "leg_of_day", "is_first_leg"],
    "Météo au départ": ["o_wind_kt", "o_gust_kt", "o_visibility_km", "o_precip_mm", "o_ceiling_ft",
                        "o_thunderstorm", "o_sev", "o_sev_max3h", "origin_day_sev_sum"],
    "Météo à l'arrivée (régulation ATFM)": ["d_wind_kt", "d_gust_kt", "d_visibility_km", "d_precip_mm",
                                             "d_ceiling_ft", "d_thunderstorm", "d_sev", "d_sev_max3h"],
    "Congestion aéroport / ATC": ["o_sched_deps_hour", "d_sched_arrs_hour", "origin_mean_dep_delay_prev_day"],
    "Historique de la ligne": ["route_mean_arr_delay_28d", "flight_delay15_rate_28d", "origin", "dest",
                               "distance_km", "sched_block_min"],
    "Calendrier / horaire": ["dep_hour", "dow", "month", "is_weekend"],
}
FEATURE_TO_GROUP = {f: g for g, fs in FACTOR_GROUPS.items() for f in fs}


def weather_severity(w: pd.DataFrame) -> pd.Series:
    gust = w["gust_kt"].fillna(w["wind_kt"])
    return (3.0 * w["thunderstorm"].fillna(0)
            + 1.5 * (w["visibility_km"] < 1.0) + 0.8 * (w["visibility_km"] < 3.0)
            + 0.06 * np.maximum(gust - 25, 0)
            + 0.4 * (w["precip_mm"] > 2) + 0.6 * (w["ceiling_ft"] < 300) + 1.0 * w["snow"].fillna(0))


def _weather_table(weather: pd.DataFrame) -> pd.DataFrame:
    w = weather.copy()
    w["ts"] = pd.to_datetime(w["ts"])
    w["sev"] = weather_severity(w)
    w = w.sort_values(["airport", "ts"])
    w["sev_max3h"] = w.groupby("airport")["sev"].transform(lambda s: s.rolling(3, center=True, min_periods=1).max())
    w["date"] = w["ts"].dt.date
    w["day_sev_sum"] = w.groupby(["airport", "date"])["sev"].transform("sum")
    return w


def _rolling_history(df: pd.DataFrame, keys: list[str], value: str, window: int, name: str) -> pd.DataFrame:
    """Moyenne glissante sur les `window` jours PRÉCÉDENTS (jour courant exclu -> pas de fuite)."""
    daily = df.groupby(keys + ["flight_date"])[value].agg(["sum", "count"]).reset_index()
    daily = daily.sort_values(keys + ["flight_date"])
    g = daily.groupby(keys)
    s = g["sum"].transform(lambda x: x.shift(1).rolling(window, min_periods=1).sum())
    c = g["count"].transform(lambda x: x.shift(1).rolling(window, min_periods=1).sum())
    daily[name] = s / c
    return daily[keys + ["flight_date", name]]


def build_features(flights: pd.DataFrame, weather: pd.DataFrame) -> pd.DataFrame:
    f = flights.copy()
    for c in ["sched_dep", "sched_arr"]:
        f[c] = pd.to_datetime(f[c])
    f["flight_date"] = pd.to_datetime(f["flight_date"]).dt.date
    f = f[f["cancelled"] == 0].sort_values(["tail_number", "sched_dep"]).reset_index(drop=True)

    # --- calendrier & programme
    f["dep_hour"] = f["sched_dep"].dt.hour
    f["dow"] = f["sched_dep"].dt.dayofweek
    f["month"] = f["sched_dep"].dt.month
    f["is_weekend"] = (f["dow"] >= 5).astype(int)
    f["sched_block_min"] = (f["sched_arr"] - f["sched_dep"]).dt.total_seconds() / 60

    # --- rotation (même avion, même journée)
    grp = f.groupby(["tail_number", "flight_date"])
    f["leg_of_day"] = grp.cumcount()
    f["is_first_leg"] = (f["leg_of_day"] == 0).astype(int)
    prev_arr = grp["sched_arr"].shift()
    f["turn_slack_min"] = (f["sched_dep"] - prev_arr).dt.total_seconds() / 60 - OPS.min_turn_min
    f["prev_leg_dep_delay"] = grp["dep_delay"].shift()
    f["inbound_reactionary_est"] = np.maximum(
        0, f["prev_leg_dep_delay"] - OPS.enroute_recovery_min - f["turn_slack_min"])

    # --- météo origine / destination
    w = _weather_table(weather)
    wcols = ["wind_kt", "gust_kt", "visibility_km", "precip_mm", "ceiling_ft", "thunderstorm", "sev", "sev_max3h"]
    f["dep_h"] = f["sched_dep"].dt.floor("h")
    f["arr_h"] = f["sched_arr"].dt.floor("h")
    wi = w.set_index(["airport", "ts"])
    o = wi[wcols].reindex(pd.MultiIndex.from_arrays([f["origin"], f["dep_h"]])).add_prefix("o_")
    d = wi[wcols].reindex(pd.MultiIndex.from_arrays([f["dest"], f["arr_h"]])).add_prefix("d_")
    f = pd.concat([f, o.reset_index(drop=True), d.reset_index(drop=True)], axis=1)
    day_sev = w.drop_duplicates(["airport", "date"]).set_index(["airport", "date"])["day_sev_sum"]
    f["origin_day_sev_sum"] = day_sev.reindex(pd.MultiIndex.from_arrays([f["origin"], f["flight_date"]])).values

    # --- congestion programmée
    f["o_sched_deps_hour"] = f.groupby(["origin", "dep_h"])["flight_id"].transform("count")
    f["d_sched_arrs_hour"] = f.groupby(["dest", "arr_h"])["flight_id"].transform("count")

    # --- historique (jours précédents uniquement)
    f["is_delay15"] = (f["arr_delay"] >= OPS.otp_threshold_min).astype(float)
    hist = [
        (_rolling_history(f, ["origin", "dest"], "arr_delay", 28, "route_mean_arr_delay_28d"), ["origin", "dest"]),
        (_rolling_history(f, ["flight_number"], "is_delay15", 28, "flight_delay15_rate_28d"), ["flight_number"]),
        (_rolling_history(f, ["origin"], "dep_delay", 1, "origin_mean_dep_delay_prev_day"), ["origin"]),
    ]
    for h, keys in hist:
        f = f.merge(h, on=keys + ["flight_date"], how="left")

    for c in CATEGORICAL:
        f[c] = f[c].astype("category")
    return f.drop(columns=["dep_h", "arr_h"])
