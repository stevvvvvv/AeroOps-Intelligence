"""Générateur de données d'exploitation réalistes (mode démo / hors-ligne).

Pourquoi un générateur ? Les sources réelles (BTS, OpenSky, METAR) demandent
un accès réseau et, pour OpenSky, un compte. Ce module produit un jeu de
données cohérent avec le même schéma, en simulant les MÉCANISMES qui créent
les retards plutôt que des retards tirés au hasard :

* un programme de vols saisonnier par avion (rotations hub -> escale -> hub),
  avec des marges de demi-tour variables ;
* une météo horaire par aéroport (orages convectifs l'été, brouillard matinal,
  mistral, fronts pluvieux) ;
* des retards primaires (météo, contrôle aérien/ATFM, congestion, technique,
  jours de grève ATC) ;
* la propagation du retard le long des rotations (retard réactionnaire),
  qui représente en Europe une part majeure des minutes de retard.

Le modèle ML ne "voit" pas ces règles : il doit les réapprendre à partir des
données, exactement comme sur des données réelles.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..config import OPS

CARRIER = "AO"  # compagnie fictive "AeroOps Airlines"


@dataclass(frozen=True)
class Airport:
    iata: str
    icao: str
    name: str
    lat: float
    lon: float
    is_hub: int = 0
    congestion: float = 0.6     # niveau de saturation (capacité piste / ATC)
    storm_prob: float = 0.06    # probabilité quotidienne d'orage (été)
    fog_prob: float = 0.03      # probabilité quotidienne de brouillard matinal
    wind_base: float = 8.0      # vent moyen (kt)
    french: int = 1             # concerné par les grèves du contrôle aérien français


AIRPORTS: list[Airport] = [
    Airport("CDG", "LFPG", "Paris-Charles de Gaulle", 49.0097, 2.5479, 1, 1.00, 0.08, 0.04, 9),
    Airport("ORY", "LFPO", "Paris-Orly", 48.7262, 2.3652, 1, 0.80, 0.08, 0.04, 9),
    Airport("NCE", "LFMN", "Nice Côte d'Azur", 43.6584, 7.2159, 0, 0.70, 0.16, 0.01, 7),
    Airport("MRS", "LFML", "Marseille Provence", 43.4393, 5.2214, 0, 0.55, 0.12, 0.01, 14),
    Airport("LYS", "LFLL", "Lyon Saint-Exupéry", 45.7256, 5.0811, 0, 0.55, 0.14, 0.06, 7),
    Airport("TLS", "LFBO", "Toulouse Blagnac", 43.6293, 1.3638, 0, 0.55, 0.10, 0.04, 9),
    Airport("BOD", "LFBD", "Bordeaux Mérignac", 44.8283, -0.7156, 0, 0.50, 0.09, 0.07, 8),
    Airport("NTE", "LFRS", "Nantes Atlantique", 47.1532, -1.6107, 0, 0.45, 0.06, 0.05, 11),
    Airport("LHR", "EGLL", "London Heathrow", 51.4700, -0.4543, 0, 1.10, 0.05, 0.04, 11, 0),
    Airport("AMS", "EHAM", "Amsterdam Schiphol", 52.3086, 4.7639, 0, 0.95, 0.06, 0.04, 13, 0),
    Airport("FRA", "EDDF", "Frankfurt", 50.0379, 8.5622, 0, 0.90, 0.12, 0.04, 8, 0),
    Airport("MAD", "LEMD", "Madrid Barajas", 40.4719, -3.5626, 0, 0.75, 0.08, 0.01, 8, 0),
    Airport("BCN", "LEBL", "Barcelona El Prat", 41.2971, 2.0785, 0, 0.80, 0.09, 0.01, 9, 0),
    Airport("FCO", "LIRF", "Rome Fiumicino", 41.8003, 12.2389, 0, 0.75, 0.10, 0.02, 9, 0),
    Airport("LIS", "LPPT", "Lisbon Humberto Delgado", 38.7742, -9.1342, 0, 0.90, 0.04, 0.03, 11, 0),
    Airport("ATH", "LGAV", "Athens", 37.9364, 23.9445, 0, 0.60, 0.04, 0.00, 12, 0),
    Airport("RAK", "GMMX", "Marrakech Menara", 31.6069, -8.0363, 0, 0.45, 0.03, 0.00, 7, 0),
]
AP = {a.iata: a for a in AIRPORTS}

HUB_NETWORK = {
    "CDG": ["NCE", "MRS", "LYS", "TLS", "BOD", "NTE", "LHR", "AMS", "FRA", "MAD", "BCN", "FCO", "LIS", "ATH"],
    "ORY": ["NCE", "MRS", "TLS", "BOD", "MAD", "BCN", "FCO", "LIS", "RAK"],
}
AC_TYPES = [("A319", 144, 0.2), ("A320", 180, 0.55), ("A321", 220, 0.25)]


def haversine_km(a: str, b: str) -> float:
    p, q = AP[a], AP[b]
    r = 6371.0
    dlat, dlon = math.radians(q.lat - p.lat), math.radians(q.lon - p.lon)
    h = math.sin(dlat / 2) ** 2 + math.cos(math.radians(p.lat)) * math.cos(math.radians(q.lat)) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def _round5(minutes: float) -> int:
    return int(5 * round(minutes / 5))


# --------------------------------------------------------------------------- flotte & programme
def build_fleet(rng: np.random.Generator, n_cdg: int = 26, n_ory: int = 14, spares=(("CDG", 2), ("ORY", 1))) -> pd.DataFrame:
    rows, letters = [], "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    idx = 0

    def next_reg():
        nonlocal idx
        reg = f"F-HO{letters[idx // 26]}{letters[idx % 26]}"
        idx += 1
        return reg

    types, seats, probs = zip(*AC_TYPES)
    for base, n in (("CDG", n_cdg), ("ORY", n_ory)):
        for _ in range(n):
            k = rng.choice(len(types), p=probs)
            rows.append((next_reg(), types[k], seats[k], base, 0))
    for base, n in spares:
        for _ in range(n):
            rows.append((next_reg(), "A320", 180, base, 1))
    return pd.DataFrame(rows, columns=["tail_number", "ac_type", "seats", "base", "is_spare"])


def build_schedule_template(fleet: pd.DataFrame, rng: np.random.Generator) -> pd.DataFrame:
    """Programme saisonnier : chaque avion répète la même journée type (comme un programme IATA)."""
    slack_values = np.array([0, 5, 10, 15, 20, 30, 45])
    slack_probs = np.array([0.12, 0.20, 0.22, 0.18, 0.12, 0.10, 0.06])
    rows, fn = [], 1000
    for tail in fleet[fleet.is_spare == 0].itertuples():
        hub = tail.base
        t = 6 * 60 + _round5(rng.uniform(0, 90))  # minutes depuis minuit
        leg = 0
        while True:
            dest = rng.choice(HUB_NETWORK[hub])
            dist = haversine_km(hub, dest)
            block = _round5(dist / 760 * 60 + 30 + rng.uniform(0, 10))
            out_turn = OPS.min_turn_min + int(rng.choice(slack_values, p=slack_probs))
            back_arr = t + block + out_turn + block
            if back_arr > 22 * 60 + 45:
                break
            for o, d, dep in ((hub, dest, t), (dest, hub, t + block + out_turn)):
                rows.append(dict(tail_number=tail.tail_number, leg_index=leg, origin=o, dest=d,
                                 dep_min=dep, arr_min=dep + block, distance_km=round(dist, 1),
                                 flight_number=f"{CARRIER}{fn}", seats=tail.seats))
                fn += 1
                leg += 1
            t = back_arr + OPS.min_turn_min + int(rng.choice(slack_values, p=slack_probs))
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------- météo
def build_weather(start: pd.Timestamp, end: pd.Timestamp, rng: np.random.Generator) -> pd.DataFrame:
    hours = pd.date_range(start, end + pd.Timedelta(days=1), freq="h", inclusive="left")
    n = len(hours)
    doy = hours.dayofyear.values
    hod = hours.hour.values
    days = pd.date_range(start, end, freq="D")
    season = 0.7 + 0.5 * np.clip((pd.DatetimeIndex(days).month.values - 5) / 2.5, 0, 1)  # orages : pic juillet-août
    frames = []
    for ap in AIRPORTS:
        temp = (27 - 0.55 * (ap.lat - 38)) + 6 * np.sin((doy - 110) / 365 * 2 * np.pi) \
            + 5 * np.sin((hod - 9) / 24 * 2 * np.pi) + rng.normal(0, 1.5, n)
        # vent : processus AR(1) log-normal + épisodes de vent fort
        z = np.zeros(n)
        eps = rng.normal(0, 0.18, n)
        for i in range(1, n):
            z[i] = 0.93 * z[i - 1] + eps[i]
        wind = ap.wind_base * np.exp(z) * (1 + 0.25 * np.sin((hod - 9) / 24 * 2 * np.pi))
        vis = np.full(n, 10.0)
        precip = np.zeros(n)
        ceiling = np.full(n, 9999.0)
        thunder = np.zeros(n, dtype=int)
        gust_extra = np.zeros(n)
        for d_i in range(len(days)):
            base_h = d_i * 24
            if rng.random() < ap.storm_prob * season[d_i]:  # orage convectif (après-midi)
                s = int(np.clip(rng.normal(16, 2.5), 11, 21))
                dur = int(rng.integers(1, 5))
                sl = slice(base_h + s, base_h + s + dur)
                thunder[sl] = 1
                precip[sl] = rng.uniform(4, 20)
                vis[sl] = rng.uniform(1.5, 5)
                ceiling[sl] = rng.uniform(800, 2500)
                gust_extra[sl] = rng.uniform(15, 30)
            if rng.random() < 0.08:  # front pluvieux
                s, dur = int(rng.integers(0, 18)), int(rng.integers(4, 11))
                sl = slice(base_h + s, base_h + s + dur)
                precip[sl] = np.maximum(precip[sl], rng.uniform(0.5, 3))
                vis[sl] = np.minimum(vis[sl], rng.uniform(4, 8))
                ceiling[sl] = np.minimum(ceiling[sl], rng.uniform(1200, 3000))
            if rng.random() < ap.fog_prob:  # brouillard matinal (LVP)
                s, dur = int(rng.integers(3, 6)), int(rng.integers(2, 6))
                sl = slice(base_h + s, base_h + s + dur)
                vis[sl] = rng.uniform(0.15, 1.0)
                ceiling[sl] = rng.uniform(100, 300)
        gust = np.where(wind + gust_extra > 15, (wind + gust_extra) * rng.uniform(1.3, 1.6, n), np.nan)
        frames.append(pd.DataFrame({
            "airport": ap.iata, "ts": hours, "temp_c": temp.round(1),
            "wind_kt": (wind + gust_extra * 0.5).round(1), "gust_kt": np.round(gust, 1),
            "visibility_km": vis.round(2), "precip_mm": precip.round(1), "ceiling_ft": ceiling.round(0),
            "thunderstorm": thunder, "snow": 0,
        }))
    return pd.concat(frames, ignore_index=True)


def weather_severity(w: pd.DataFrame) -> pd.Series:
    """Indice de sévérité opérationnelle (0 = rien, >3 = très perturbant)."""
    gust = w["gust_kt"].fillna(w["wind_kt"])
    return (3.0 * w["thunderstorm"]
            + 1.5 * (w["visibility_km"] < 1.0) + 0.8 * (w["visibility_km"] < 3.0)
            + 0.06 * np.maximum(gust - 25, 0)
            + 0.4 * (w["precip_mm"] > 2) + 0.6 * (w["ceiling_ft"] < 300))


# --------------------------------------------------------------------------- vols & retards
HOUR_PEAK = np.array([0.4, 0.3, 0.3, 0.3, 0.3, 0.5, 0.9, 1.4, 1.5, 1.3, 1.0, 1.0,
                      1.1, 1.0, 1.0, 1.1, 1.2, 1.4, 1.5, 1.4, 1.2, 1.0, 0.8, 0.6])
DOW_FACTOR = np.array([1.05, 0.95, 0.95, 1.0, 1.2, 0.9, 1.15])  # lun..dim


def generate(start: str = "2026-05-01", end: str = "2026-08-31", seed: int = 7) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end)
    fleet = build_fleet(rng)
    template = build_schedule_template(fleet, rng)
    weather = build_weather(start_ts, end_ts, rng)
    weather["sev"] = weather_severity(weather)
    sev = weather.set_index(["airport", "ts"])["sev"]

    days = pd.date_range(start_ts, end_ts, freq="D")
    strike_days = set(rng.choice(days, size=3, replace=False))  # grèves ATC françaises

    out = []
    for day in days:
        strike = day in strike_days
        dow = day.dayofweek
        legs = template.copy()
        legs["sched_dep"] = day + pd.to_timedelta(legs["dep_min"], unit="min")
        legs["sched_arr"] = day + pd.to_timedelta(legs["arr_min"], unit="min")
        legs = legs.sort_values(["tail_number", "leg_index"])
        dep_h = legs["sched_dep"].dt.floor("h")
        arr_h = legs["sched_arr"].dt.floor("h")
        sev_o = sev.reindex(list(zip(legs["origin"], dep_h))).fillna(0).values
        sev_d = sev.reindex(list(zip(legs["dest"], arr_h))).fillna(0).values
        n = len(legs)
        cong = np.array([AP[o].congestion for o in legs["origin"]]) * HOUR_PEAK[legs["sched_dep"].dt.hour.values] * DOW_FACTOR[dow]
        french = np.array([AP[o].french or AP[d].french for o, d in zip(legs["origin"], legs["dest"])])

        wx = np.where(sev_o > 0, sev_o * rng.uniform(6, 18, n) * rng.lognormal(0, 0.4, n), 0.0)
        regulated = rng.random(n) < np.minimum(0.9, 0.25 * sev_d)       # régulation ATFM à destination
        nas = np.where(regulated, sev_d * rng.uniform(8, 20, n), 0.0)
        nas += np.where(rng.random(n) < 0.45, rng.exponential(5.0 * cong), 0.0)
        if strike:
            nas += np.where((french == 1) & (rng.random(n) < 0.6), rng.exponential(45, n), 0.0)
        carrier = np.where(rng.random(n) < 0.07, rng.lognormal(3.2, 0.7, n), 0.0)   # incident technique/escale
        jitter = rng.normal(-2.5, 3.5, n)

        own = wx + nas + carrier + jitter
        dep_delay = np.zeros(n)
        arr_delay = np.zeros(n)
        react = np.zeros(n)
        tails = legs["tail_number"].values
        sched_dep = legs["sched_dep"].values
        sched_arr = legs["sched_arr"].values
        holding = np.where(sev_d > 0, sev_d * rng.uniform(2, 7, n), 0.0)
        enroute = rng.normal(0, 4, n) - OPS.enroute_recovery_min * rng.uniform(0.5, 1.5, n)
        for i in range(n):
            if i > 0 and tails[i] == tails[i - 1]:
                slack = (sched_dep[i] - sched_arr[i - 1]) / np.timedelta64(1, "m") - OPS.min_turn_min
                react[i] = max(0.0, arr_delay[i - 1] - slack)
            r, o = react[i], own[i]
            d = max(r, o) + 0.3 * min(r, max(o, 0.0))
            dep_delay[i] = max(d, -10.0)
            arr_delay[i] = max(dep_delay[i] + enroute[i] + holding[i], -25.0)

        # attribution des causes (convention BTS : renseignée si retard arrivée >= 15 min)
        pos = np.maximum(arr_delay, 0)
        late_ac = np.minimum(react, pos)
        rest = pos - late_ac
        comp = np.vstack([np.maximum(carrier + np.maximum(jitter, 0), 0), wx + holding, nas])
        share = comp / np.where(comp.sum(0) > 0, comp.sum(0), 1)
        share[:, comp.sum(0) == 0] = np.array([[1], [0], [0]])
        mask = arr_delay >= OPS.otp_threshold_min
        legs = legs.assign(
            flight_date=day.date(), carrier=CARRIER,
            dep_delay=dep_delay.round(0), arr_delay=arr_delay.round(0),
            actual_dep=legs["sched_dep"] + pd.to_timedelta(dep_delay.round(0), unit="min"),
            actual_arr=legs["sched_arr"] + pd.to_timedelta(arr_delay.round(0), unit="min"),
            cancelled=0,
            delay_carrier=np.where(mask, rest * share[0], 0).round(0),
            delay_weather=np.where(mask, rest * share[1], 0).round(0),
            delay_nas=np.where(mask, rest * share[2], 0).round(0),
            delay_late_aircraft=np.where(mask, late_ac, 0).round(0),
        )
        legs["flight_id"] = legs["flight_number"] + "-" + day.strftime("%Y%m%d")
        out.append(legs)

    flights = pd.concat(out, ignore_index=True)
    flights = flights[["flight_id", "flight_date", "carrier", "flight_number", "tail_number", "origin", "dest",
                       "sched_dep", "sched_arr", "actual_dep", "actual_arr", "dep_delay", "arr_delay",
                       "distance_km", "seats", "cancelled", "delay_carrier", "delay_weather", "delay_nas",
                       "delay_late_aircraft"]]
    airports = pd.DataFrame([dict(iata=a.iata, icao=a.icao, name=a.name, lat=a.lat, lon=a.lon, is_hub=a.is_hub)
                             for a in AIRPORTS])
    return {"airports": airports, "aircraft": fleet, "flights": flights,
            "weather_hourly": weather.drop(columns="sev"),
            "_meta": pd.DataFrame({"strike_day": sorted(pd.Timestamp(d).date() for d in strike_days)})}
