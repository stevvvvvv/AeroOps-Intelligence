import pandas as pd

from aeroops.config import OPS
from aeroops.ops.simulation import Leg, propagate

T0 = pd.Timestamp("2026-07-01 06:00")


def chain(slacks: list[int], block: int = 60) -> list[Leg]:
    """Rotation fictive : leg de `block` min, demi-tour = MTT + slack."""
    legs, t = [], T0
    for i, s in enumerate([0] + slacks):
        if i:
            t = legs[-1].sched_arr + pd.Timedelta(minutes=OPS.min_turn_min + s)
        legs.append(Leg(f"F{i}", f"AO{i}", "F-TEST", "CDG" if i % 2 == 0 else "NCE", "NCE" if i % 2 == 0 else "CDG",
                        t, t + pd.Timedelta(minutes=block), 700, 180))
    return legs


def test_delay_absorbed_by_slack():
    res = propagate(chain([60]), "F-TEST", 30)
    assert res[0].dep_delay == 30
    assert res[1].dep_delay == 0  # 60 min de marge > retard résiduel


def test_delay_propagates_minus_slack_and_recovery():
    res = propagate(chain([10, 10]), "F-TEST", 60)
    expected_leg1 = 60 - OPS.enroute_recovery_min - 10
    assert res[1].dep_delay == expected_leg1
    assert res[2].dep_delay == expected_leg1 - OPS.enroute_recovery_min - 10


def test_quick_turn_reduces_cascade():
    normal = propagate(chain([0, 0, 0]), "F-TEST", 60)
    quick = propagate(chain([0, 0, 0]), "F-TEST", 60, min_turn=OPS.quick_turn_min)
    assert sum(r.arr_delay for r in quick) < sum(r.arr_delay for r in normal)


def test_no_negative_delays():
    res = propagate(chain([0, 0]), "F-TEST", 0)
    assert all(r.dep_delay >= 0 and r.arr_delay >= 0 for r in res)
