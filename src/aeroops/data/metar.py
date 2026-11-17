"""Météo historique réelle : observations METAR via l'Iowa Environmental Mesonet.

L'IEM archive les METAR mondiaux (ASOS/AWOS) et les expose sans compte.
On agrège à l'heure pleine pour aligner avec les vols.
Stations : code ICAO hors US (ex. LFPG), code FAA à 3 lettres aux US (ex. ATL).
"""
from __future__ import annotations

import io

import httpx
import numpy as np
import pandas as pd

IEM_URL = "https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py"
FIELDS = ["tmpf", "sknt", "gust", "vsby", "skyl1", "p01i", "wxcodes"]


def fetch_station(station: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
    params: list[tuple[str, str]] = [("station", station)] + [("data", f) for f in FIELDS] + [
        ("year1", str(start.year)), ("month1", str(start.month)), ("day1", str(start.day)),
        ("year2", str(end.year)), ("month2", str(end.month)), ("day2", str(end.day)),
        ("tz", "Etc/UTC"), ("format", "onlycomma"), ("latlon", "no"),
        ("missing", "empty"), ("trace", "empty"), ("report_type", "3"), ("report_type", "4"),
    ]
    r = httpx.get(IEM_URL, params=params, timeout=180)
    r.raise_for_status()
    return pd.read_csv(io.StringIO(r.text), parse_dates=["valid"])


def to_hourly(obs: pd.DataFrame, airport_iata: str) -> pd.DataFrame:
    df = obs.copy()
    for c in ["tmpf", "sknt", "gust", "vsby", "skyl1", "p01i"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    wx = df["wxcodes"].fillna("")
    df["thunderstorm"] = wx.str.contains("TS").astype(int)
    df["snow"] = wx.str.contains("SN").astype(int)
    df["ts"] = df["valid"].dt.floor("h")
    agg = df.groupby("ts").agg(
        temp_c=("tmpf", lambda s: (s.mean() - 32) * 5 / 9),
        wind_kt=("sknt", "mean"), gust_kt=("gust", "max"),
        visibility_km=("vsby", lambda s: s.min() * 1.609344),
        precip_mm=("p01i", lambda s: np.nan_to_num(s.max()) * 25.4),
        ceiling_ft=("skyl1", "min"),           # base du 1er niveau nuageux (approximation du plafond)
        thunderstorm=("thunderstorm", "max"), snow=("snow", "max"),
    ).reset_index()
    agg["ceiling_ft"] = agg["ceiling_ft"].fillna(9999)
    agg["visibility_km"] = agg["visibility_km"].fillna(10).clip(upper=10)
    agg.insert(0, "airport", airport_iata)
    return agg.round(2)


def fetch_airports(airports: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp, us: bool = False) -> pd.DataFrame:
    frames = []
    for row in airports.itertuples():
        station = row.iata if us else row.icao
        try:
            frames.append(to_hourly(fetch_station(station, start, end), row.iata))
        except Exception as exc:  # une station manquante ne doit pas bloquer le pipeline
            print(f"[metar] {station}: {exc}")
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
