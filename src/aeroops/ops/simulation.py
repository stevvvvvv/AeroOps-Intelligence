"""Retards en cascade et simulation de scénarios de réorganisation.

Modèle de propagation (standard en recherche opérationnelle aérienne) :
    retard_arrivée(i)   = max(0, retard_départ(i) - récupération_en_vol)
    marge(i+1)          = départ_prog(i+1) - arrivée_prog(i) - temps_demi_tour_min
    retard_départ(i+1)  = max(retard_propre(i+1), retard_arrivée(i) - marge(i+1))

Pour un vol perturbé, on compare plusieurs décisions qu'un centre de contrôle
des opérations (OCC) prendrait réellement, chacune chiffrée en euros :
  0. ne rien faire (absorption naturelle par les marges) ;
  1. demi-tours accélérés (moyens sol renforcés) ;
  2. avion de réserve au hub ;
  3. échange d'avion (tail swap) avec un appareil disponible au sol ;
  4. annulation d'un aller-retour pour "remettre l'avion à l'heure".
Limites assumées : la légalité des équipages (FTL) et la correspondance des
passagers ne sont pas modélisées.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from ..config import CURFEWS, OPS, eu261_amount, EU261_THRESHOLD_MIN


@dataclass
class Leg:
    flight_id: str
    flight_number: str
    tail: str
    origin: str
    dest: str
    sched_dep: pd.Timestamp
    sched_arr: pd.Timestamp
    distance_km: float
    seats: int
    own_delay: float = 0.0


@dataclass
class LegResult:
    leg: Leg
    tail: str
    dep_delay: float = 0.0
    arr_delay: float = 0.0
    status: str = "operated"     # operated | cancelled | reassigned

    def as_dict(self) -> dict:
        l = self.leg
        return {"flight_id": l.flight_id, "flight_number": l.flight_number, "tail_number": self.tail,
                "original_tail": l.tail, "origin": l.origin, "dest": l.dest,
                "sched_dep": l.sched_dep.isoformat(), "sched_arr": l.sched_arr.isoformat(),
                "dep_delay": round(self.dep_delay), "arr_delay": round(self.arr_delay), "status": self.status}


@dataclass
class Scenario:
    key: str
    label: str
    description: str
    feasible: bool = True
    legs: list[LegResult] = field(default_factory=list)
    action_cost: float = 0.0

    def summary(self) -> dict:
        pax = lambda r: r.leg.seats * OPS.load_factor
        op = [r for r in self.legs if r.status != "cancelled"]
        cancelled = [r for r in self.legs if r.status == "cancelled"]
        delay_cost = sum(max(r.arr_delay, 0) for r in op) * OPS.cost_per_delay_min
        eu261 = sum(pax(r) * eu261_amount(r.leg.distance_km) for r in op if r.arr_delay >= EU261_THRESHOLD_MIN)
        eu261 += sum(pax(r) * eu261_amount(r.leg.distance_km) for r in cancelled)
        cancel_cost = sum(pax(r) * OPS.cancel_cost_per_pax for r in cancelled)
        curfew = [r for r in op if _breaches_curfew(r)]
        costs = {"retards": delay_cost, "eu261": eu261, "annulations": cancel_cost,
                 "couvre_feu": len(curfew) * OPS.curfew_penalty, "action": self.action_cost}
        return {
            "key": self.key, "label": self.label, "description": self.description, "feasible": self.feasible,
            "total_delay_min": round(sum(max(r.arr_delay, 0) for r in op)),
            "flights_impacted": sum(1 for r in op if r.arr_delay >= OPS.otp_threshold_min),
            "pax_delayed15": round(sum(pax(r) for r in op if r.arr_delay >= OPS.otp_threshold_min)),
            "pax_eu261": round(sum(pax(r) for r in op if r.arr_delay >= EU261_THRESHOLD_MIN)
                               + sum(pax(r) for r in cancelled)),
            "flights_cancelled": len(cancelled), "curfew_breaches": len(curfew),
            "costs": {k: round(v) for k, v in costs.items()}, "total_cost": round(sum(costs.values())),
            "legs": [r.as_dict() for r in self.legs],
        }


def _breaches_curfew(r: LegResult) -> bool:
    if r.leg.dest not in CURFEWS:
        return False
    hh, mm = map(int, CURFEWS[r.leg.dest].split(":"))
    limit = r.leg.sched_arr.normalize() + pd.Timedelta(hours=hh, minutes=mm)
    return r.leg.sched_arr + pd.Timedelta(minutes=r.arr_delay) > limit


def legs_from_frame(df: pd.DataFrame) -> list[Leg]:
    df = df.sort_values(["tail_number", "sched_dep"])
    own = df["own_delay"] if "own_delay" in df else pd.Series(0.0, index=df.index)
    return [Leg(r.flight_id, r.flight_number, r.tail_number, r.origin, r.dest, pd.Timestamp(r.sched_dep),
                pd.Timestamp(r.sched_arr), float(r.distance_km), int(r.seats or OPS.seats), float(o))
            for r, o in zip(df.itertuples(), own.clip(lower=0))]


def propagate(chain: list[Leg], tail: str, initial_dep_delay: float, min_turn: float = OPS.min_turn_min,
              ready_delay_before_first: float | None = None) -> list[LegResult]:
    """Propage un retard le long d'une chaîne de legs opérés par un même avion."""
    out: list[LegResult] = []
    prev: LegResult | None = None
    for k, leg in enumerate(chain):
        if k == 0:
            dep = max(initial_dep_delay, leg.own_delay)
            if ready_delay_before_first is not None:
                dep = max(dep, ready_delay_before_first)
        else:
            slack = (leg.sched_dep - prev.leg.sched_arr).total_seconds() / 60 - min_turn
            dep = max(leg.own_delay, prev.arr_delay - slack, 0.0)
        arr = max(dep - OPS.enroute_recovery_min, 0.0) if dep > 0 else 0.0
        prev = LegResult(leg, tail, dep, arr, "operated" if tail == leg.tail else "reassigned")
        out.append(prev)
    return out


class DisruptionSimulator:
    def __init__(self, day_flights: pd.DataFrame, aircraft: pd.DataFrame):
        self.legs = legs_from_frame(day_flights)
        self.by_tail: dict[str, list[Leg]] = {}
        for l in self.legs:
            self.by_tail.setdefault(l.tail, []).append(l)
        self.aircraft = aircraft.set_index("tail_number")

    def _locate(self, flight_id: str) -> tuple[str, int]:
        for tail, chain in self.by_tail.items():
            for i, l in enumerate(chain):
                if l.flight_id == flight_id:
                    return tail, i
        raise KeyError(f"Vol {flight_id} introuvable pour cette journée")

    def cascade(self, flight_id: str, delay_min: float) -> dict:
        tail, i = self._locate(flight_id)
        return self._no_action(tail, i, delay_min).summary()

    # ---------------------------------------------------------------- scénarios
    def _no_action(self, tail, i, d) -> Scenario:
        s = Scenario("no_action", "Aucune action", "Le retard est absorbé uniquement par les marges de rotation.")
        s.legs = propagate(self.by_tail[tail][i:], tail, d)
        return s

    def _quick_turn(self, tail, i, d) -> Scenario:
        s = Scenario("quick_turn", "Demi-tours accélérés",
                     f"Moyens sol renforcés : demi-tour ramené de {OPS.min_turn_min} à {OPS.quick_turn_min} min sur les escales suivantes.")
        s.legs = propagate(self.by_tail[tail][i:], tail, d, min_turn=OPS.quick_turn_min)
        compressed = sum(1 for r in s.legs[:-1] if r.arr_delay > 0)  # escales où l'on accélère
        s.action_cost = OPS.quick_turn_cost * max(compressed, 1)
        return s

    def _spare(self, tail, i, d) -> Scenario:
        chain = self.by_tail[tail]
        spares = self.aircraft[self.aircraft["is_spare"] == 1]
        for j in range(i + 1, len(chain)):
            avail = spares[spares["base"] == chain[j].origin]
            if len(avail):
                spare = avail.index[0]
                s = Scenario("spare", f"Avion de réserve {spare}",
                             f"{spare} (réserve à {chain[j].origin}) reprend la rotation à partir du {chain[j].flight_number}.")
                s.legs = propagate(chain[i:j], tail, d) + propagate(chain[j:], spare, 0.0)
                s.action_cost = OPS.spare_aircraft_cost
                return s
        return Scenario("spare", "Avion de réserve", "Aucun avion de réserve positionné sur la rotation.", feasible=False)

    def _swap(self, tail, i, d) -> Scenario:
        chain = self.by_tail[tail]
        delayed = propagate(chain[i:], tail, d)
        seats = chain[i].seats
        best: tuple[float, Scenario] | None = None
        for j in range(i + 1, len(chain)):
            station, t_j = chain[j].origin, chain[j].sched_dep
            t_arrival_late = chain[j - 1].sched_arr + pd.Timedelta(minutes=delayed[j - 1 - i].arr_delay)
            for t2, c2 in self.by_tail.items():
                if t2 == tail or self.aircraft.loc[t2, "seats"] < seats * OPS.load_factor:
                    continue
                # T2 doit être au sol à la station, disponible avant t_j, avec un départ ultérieur à céder
                arrived = [k for k, l in enumerate(c2) if l.dest == station and
                           l.sched_arr + pd.Timedelta(minutes=OPS.min_turn_min) <= t_j]
                if not arrived:
                    continue
                k = arrived[-1]
                if k + 1 < len(c2) and c2[k + 1].sched_dep <= t_j:
                    continue  # T2 repart avant : pas disponible
                rest2 = c2[k + 1:]
                if rest2 and rest2[0].origin != station:
                    continue
                ready = (t_arrival_late + pd.Timedelta(minutes=OPS.min_turn_min) - rest2[0].sched_dep).total_seconds() / 60 \
                    if rest2 else 0.0
                s = Scenario("swap", f"Échange d'avion {tail} ↔ {t2}",
                             f"À {station}, {t2} (au sol) prend le {chain[j].flight_number} et la suite de la rotation ; "
                             f"{tail} récupère le programme de {t2}" + (f" à partir du {rest2[0].flight_number}." if rest2 else "."))
                s.legs = delayed[: j - i] + propagate(chain[j:], t2, 0.0) + \
                    (propagate(rest2, tail, 0.0, ready_delay_before_first=max(ready, 0.0)) if rest2 else [])
                s.action_cost = OPS.swap_cost
                cost = s.summary()["total_cost"]
                if best is None or cost < best[0]:
                    best = (cost, s)
        return best[1] if best else Scenario("swap", "Échange d'avion",
                                             "Aucun appareil compatible disponible au sol sur la rotation.", feasible=False)

    def _cancel_round_trip(self, tail, i, d) -> Scenario:
        chain = self.by_tail[tail]
        for j in range(i + 1, len(chain) - 1):
            a, b = chain[j], chain[j + 1]
            if a.origin == b.dest:
                s = Scenario("cancel_rt", f"Annulation {a.flight_number}/{b.flight_number}",
                             f"Annulation de l'aller-retour {a.origin}-{a.dest}-{b.dest} pour remettre l'avion à l'heure.")
                before = propagate(chain[i:j], tail, d)
                after_chain = chain[j + 2:]
                last = before[-1]
                ready = 0.0
                if after_chain:
                    ready = (last.leg.sched_arr + pd.Timedelta(minutes=last.arr_delay + OPS.min_turn_min)
                             - after_chain[0].sched_dep).total_seconds() / 60
                s.legs = before + [LegResult(a, tail, 0, 0, "cancelled"), LegResult(b, tail, 0, 0, "cancelled")] + \
                    (propagate(after_chain, tail, 0.0, ready_delay_before_first=max(ready, 0.0)) if after_chain else [])
                return s
        return Scenario("cancel_rt", "Annulation aller-retour", "Pas d'aller-retour annulable après ce vol.", feasible=False)

    def simulate(self, flight_id: str, delay_min: float) -> dict:
        tail, i = self._locate(flight_id)
        scenarios = [f(tail, i, delay_min) for f in
                     (self._no_action, self._quick_turn, self._spare, self._swap, self._cancel_round_trip)]
        summaries = [s.summary() for s in scenarios]
        feasible = [s for s in summaries if s["feasible"]]
        best = min(feasible, key=lambda s: s["total_cost"])
        base = next(s for s in summaries if s["key"] == "no_action")
        for s in summaries:
            s["saving_vs_no_action"] = base["total_cost"] - s["total_cost"] if s["feasible"] else None
        return {"flight_id": flight_id, "tail_number": tail, "initial_delay_min": delay_min,
                "recommended": best["key"],
                "scenarios": sorted(summaries, key=lambda s: (not s["feasible"], s["total_cost"]))}
