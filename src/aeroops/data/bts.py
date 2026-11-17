"""Connecteur BTS - US DOT "Reporting Carrier On-Time Performance".

Source publique, gratuite, sans compte : un fichier ZIP par mois contenant
chaque vol intérieur US des grandes compagnies, avec immatriculation
(Tail_Number), horaires programmés/réels et causes de retard (Carrier,
Weather, NAS, Security, LateAircraft). C'est le meilleur jeu réel pour ce
projet car l'immatriculation permet de reconstruire les rotations d'avions.

Les heures BTS sont en heure LOCALE de chaque aéroport : on les convertit en
UTC grâce aux fuseaux d'OpenFlights pour que les rotations multi-fuseaux
restent cohérentes.
"""
from __future__ import annotations

import io
import zipfile

import httpx
import numpy as np
import pandas as pd

from ..config import DATA_DIR

BTS_URL = ("https://transtats.bts.gov/PREZIP/"
           "On_Time_Reporting_Carrier_On_Time_Performance_1987_present_{year}_{month}.zip")
OPENFLIGHTS_URL = "https://raw.githubusercontent.com/jpatokal/openflights/master/data/airports.dat"
MILES_TO_KM = 1.609344

USECOLS = ["FlightDate", "Reporting_Airline", "Flight_Number_Reporting_Airline", "Tail_Number", "Origin", "Dest",
           "CRSDepTime", "DepDelay", "CRSElapsedTime", "ArrDelay", "Cancelled", "Distance",
           "CarrierDelay", "WeatherDelay", "NASDelay", "SecurityDelay", "LateAircraftDelay"]


def download_month(year: int, month: int, cache: bool = True) -> pd.DataFrame:
    raw_dir = DATA_DIR / "raw" / "bts"
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = raw_dir / f"bts_{year}_{month:02d}.zip"
    if not (cache and path.exists()):
        with httpx.stream("GET", BTS_URL.format(year=year, month=month), timeout=300, follow_redirects=True) as r:
            r.raise_for_status()
            with open(path, "wb") as fh:
                for chunk in r.iter_bytes():
                    fh.write(chunk)
    with zipfile.ZipFile(path) as zf:
        csv_name = next(n for n in zf.namelist() if n.endswith(".csv"))
        with zf.open(csv_name) as fh:
            return pd.read_csv(fh, usecols=USECOLS, dtype={"CRSDepTime": str, "Tail_Number": str}, low_memory=False)


def load_reference_airports(iatas: set[str] | None = None) -> pd.DataFrame:
    """Coordonnées, ICAO et fuseau horaire (OpenFlights)."""
    cols = ["id", "name", "city", "country", "iata", "icao", "lat", "lon", "alt", "utc_offset", "dst", "tz", "type", "source"]
    text = httpx.get(OPENFLIGHTS_URL, timeout=60).text
    ref = pd.read_csv(io.StringIO(text), header=None, names=cols, na_values="\\N")
    ref = ref[ref["iata"].notna() & ref["tz"].notna()]
    if iatas:
        ref = ref[ref["iata"].isin(iatas)]
    return ref.drop_duplicates("iata")[["iata", "icao", "name", "lat", "lon", "tz"]]


def _local_to_utc(local: pd.Series, tz_by_row: pd.Series) -> pd.Series:
    out = pd.Series(pd.NaT, index=local.index, dtype="datetime64[ns, UTC]")
    for tz, idx in tz_by_row.groupby(tz_by_row).groups.items():
        out.loc[idx] = local.loc[idx].dt.tz_localize(tz, ambiguous="NaT", nonexistent="shift_forward").dt.tz_convert("UTC")
    return out.dt.tz_localize(None)


def to_schema(raw: pd.DataFrame, ref: pd.DataFrame, carriers: list[str] | None = None,
              hubs: list[str] | None = None) -> dict[str, pd.DataFrame]:
    df = raw.copy()
    if carriers:
        df = df[df["Reporting_Airline"].isin(carriers)]
    df = df[df["Tail_Number"].notna() & (df["Cancelled"] == 0)]
    tz = ref.set_index("iata")["tz"]
    df = df[df["Origin"].isin(tz.index) & df["Dest"].isin(tz.index)]

    hhmm = df["CRSDepTime"].str.zfill(4).replace("2400", "2359")
    local_dep = pd.to_datetime(df["FlightDate"] + " " + hhmm, format="%Y-%m-%d %H%M")
    sched_dep = _local_to_utc(local_dep, df["Origin"].map(tz))
    sched_arr = sched_dep + pd.to_timedelta(df["CRSElapsedTime"], unit="min")

    flights = pd.DataFrame({
        "flight_id": df["Reporting_Airline"] + df["Flight_Number_Reporting_Airline"].astype(str) + "-"
                     + df["FlightDate"].str.replace("-", "") + "-" + df["Origin"],
        "flight_date": pd.to_datetime(df["FlightDate"]).dt.date,
        "carrier": df["Reporting_Airline"],
        "flight_number": df["Reporting_Airline"] + df["Flight_Number_Reporting_Airline"].astype(str),
        "tail_number": df["Tail_Number"],
        "origin": df["Origin"], "dest": df["Dest"],
        "sched_dep": sched_dep, "sched_arr": sched_arr,
        "dep_delay": df["DepDelay"], "arr_delay": df["ArrDelay"],
        "distance_km": (df["Distance"] * MILES_TO_KM).round(1),
        "seats": np.nan, "cancelled": 0,
        "delay_carrier": df["CarrierDelay"].fillna(0) + df["SecurityDelay"].fillna(0),
        "delay_weather": df["WeatherDelay"].fillna(0),
        "delay_nas": df["NASDelay"].fillna(0),
        "delay_late_aircraft": df["LateAircraftDelay"].fillna(0),
    }).dropna(subset=["sched_dep", "dep_delay", "arr_delay"])
    flights["actual_dep"] = flights["sched_dep"] + pd.to_timedelta(flights["dep_delay"], unit="min")
    flights["actual_arr"] = flights["sched_arr"] + pd.to_timedelta(flights["arr_delay"], unit="min")
    flights = flights.drop_duplicates("flight_id")

    hubs = set(hubs or flights["origin"].value_counts().head(5).index)
    airports = ref[ref["iata"].isin(set(flights["origin"]) | set(flights["dest"]))].copy()
    airports["is_hub"] = airports["iata"].isin(hubs).astype(int)
    aircraft = (flights.groupby("tail_number")["origin"].agg(lambda s: s.mode().iat[0]).rename("base").reset_index()
                .assign(ac_type="UNK", seats=150, is_spare=0))
    flights["seats"] = 150  # BTS ne fournit pas l'emport : hypothèse monocouloir
    return {"airports": airports.drop(columns="tz"), "aircraft": aircraft, "flights": flights}
