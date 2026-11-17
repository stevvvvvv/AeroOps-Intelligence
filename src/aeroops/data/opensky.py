"""Client OpenSky Network (trajectoires ADS-B réelles).

OpenSky fournit les mouvements RÉELS (premier/dernier contact ADS-B, aéroports
estimés, indicatif) par transpondeur icao24, mais pas les horaires programmés.
Usage dans AeroOps :
  1. reconstruire les rotations réelles d'une flotte (enchaînement des legs par
     icao24) et mesurer les temps au sol effectifs ;
  2. suivre en "temps réel" les legs entrants pour alimenter le modèle tactique
     (retard du leg précédent), en rapprochant l'indicatif du programme.

Authentification : depuis 2025, OpenSky utilise OAuth2 "client credentials"
(variables OPENSKY_CLIENT_ID / OPENSKY_CLIENT_SECRET). Sans identifiants,
l'accès anonyme est très limité.
"""
from __future__ import annotations

import os
import time

import httpx
import pandas as pd

API = "https://opensky-network.org/api"
TOKEN_URL = "https://auth.opensky-network.org/auth/realms/opensky-network/protocol/openid-connect/token"


class OpenSkyClient:
    def __init__(self, client_id: str | None = None, client_secret: str | None = None):
        self.client_id = client_id or os.getenv("OPENSKY_CLIENT_ID")
        self.client_secret = client_secret or os.getenv("OPENSKY_CLIENT_SECRET")
        self._token: str | None = None
        self._token_exp = 0.0
        self.http = httpx.Client(timeout=60)

    def _headers(self) -> dict:
        if not (self.client_id and self.client_secret):
            return {}
        if time.time() > self._token_exp - 60:
            r = self.http.post(TOKEN_URL, data={"grant_type": "client_credentials",
                                                "client_id": self.client_id, "client_secret": self.client_secret})
            r.raise_for_status()
            payload = r.json()
            self._token, self._token_exp = payload["access_token"], time.time() + payload.get("expires_in", 1800)
        return {"Authorization": f"Bearer {self._token}"}

    def _get(self, path: str, **params) -> list[dict]:
        r = self.http.get(f"{API}{path}", params=params, headers=self._headers())
        if r.status_code == 404:  # OpenSky renvoie 404 quand il n'y a aucun vol
            return []
        r.raise_for_status()
        return r.json() or []

    def departures(self, airport_icao: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
        """Départs d'un aéroport, découpés par tranches d'un jour (limite de l'API)."""
        rows: list[dict] = []
        t = start
        while t < end:
            t2 = min(t + pd.Timedelta(days=1), end)
            rows += self._get("/flights/departure", airport=airport_icao,
                              begin=int(t.timestamp()), end=int(t2.timestamp()))
            t = t2
        return _flights_frame(rows)

    def aircraft(self, icao24: str, start: pd.Timestamp, end: pd.Timestamp) -> pd.DataFrame:
        rows = self._get("/flights/aircraft", icao24=icao24.lower(),
                         begin=int(start.timestamp()), end=int(end.timestamp()))
        return _flights_frame(rows)

    def states(self, bbox: tuple[float, float, float, float] | None = None) -> pd.DataFrame:
        """Positions instantanées (lamin, lomin, lamax, lomax) pour le suivi live."""
        params = dict(zip(["lamin", "lomin", "lamax", "lomax"], bbox)) if bbox else {}
        r = self.http.get(f"{API}/states/all", params=params, headers=self._headers())
        r.raise_for_status()
        cols = ["icao24", "callsign", "origin_country", "time_position", "last_contact", "lon", "lat",
                "baro_altitude", "on_ground", "velocity", "true_track", "vertical_rate", "sensors",
                "geo_altitude", "squawk", "spi", "position_source"]
        states = r.json().get("states") or []
        return pd.DataFrame([s[:len(cols)] for s in states], columns=cols[:len(states[0])] if states else cols)


def _flights_frame(rows: list[dict]) -> pd.DataFrame:
    if not rows:
        return pd.DataFrame(columns=["icao24", "callsign", "origin_icao", "dest_icao", "off_block_est", "on_block_est"])
    df = pd.DataFrame(rows)
    return pd.DataFrame({
        "icao24": df["icao24"], "callsign": df["callsign"].str.strip(),
        "origin_icao": df["estDepartureAirport"], "dest_icao": df["estArrivalAirport"],
        "off_block_est": pd.to_datetime(df["firstSeen"], unit="s"),
        "on_block_est": pd.to_datetime(df["lastSeen"], unit="s"),
    })


def reconstruct_rotations(movements: pd.DataFrame, min_turn_min: int = 35) -> pd.DataFrame:
    """Enchaîne les legs par avion et calcule le temps au sol réel entre deux legs."""
    m = movements.sort_values(["icao24", "off_block_est"]).copy()
    m["prev_dest"] = m.groupby("icao24")["dest_icao"].shift()
    m["prev_on_block"] = m.groupby("icao24")["on_block_est"].shift()
    m["ground_time_min"] = (m["off_block_est"] - m["prev_on_block"]).dt.total_seconds() / 60
    m["chained"] = (m["prev_dest"] == m["origin_icao"]) & m["ground_time_min"].between(0, 12 * 60)
    m["tight_turn"] = m["chained"] & (m["ground_time_min"] < min_turn_min)
    m["leg_index"] = m.groupby(["icao24", m["off_block_est"].dt.date]).cumcount()
    return m
