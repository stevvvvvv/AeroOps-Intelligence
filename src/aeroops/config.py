"""Configuration centrale d'AeroOps Intelligence.

Toutes les hypothèses métier (temps de demi-tour minimal, coût d'une minute
de retard, barème EU261...) sont regroupées ici pour être visibles et
modifiables, plutôt que dispersées dans le code.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.getenv("AEROOPS_DATA_DIR", ROOT / "data"))
MODELS_DIR = Path(os.getenv("AEROOPS_MODELS_DIR", ROOT / "models"))
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DATA_DIR / 'aeroops.db'}")


@dataclass(frozen=True)
class OpsParams:
    # Temps de demi-tour minimal (MTT) d'un monocouloir type A320, en minutes.
    min_turn_min: int = 35
    # Demi-tour accéléré possible avec moyens supplémentaires (scénario "quick turn").
    quick_turn_min: int = 25
    # Part du retard récupérable en vol (marge de block time), en minutes par leg.
    enroute_recovery_min: float = 4.0
    # Seuil de ponctualité standard (OTP15) : un vol est "à l'heure" si retard < 15 min.
    otp_threshold_min: int = 15
    # Coût moyen d'une minute de retard pour la compagnie (hypothèse, en EUR).
    # Ordre de grandeur cohérent avec les études Eurocontrol / Univ. Westminster.
    cost_per_delay_min: float = 100.0
    # Coût d'une annulation par passager (réacheminement, hôtel, image), hors EU261.
    cancel_cost_per_pax: float = 150.0
    # Coût fixe de mobilisation d'un avion de réserve.
    spare_aircraft_cost: float = 12000.0
    # Surcoût d'un demi-tour accéléré (équipes sol renforcées).
    quick_turn_cost: float = 1500.0
    # Surcoût d'un échange d'avion (information passagers, catering, replanification).
    swap_cost: float = 2000.0
    # Pénalité si une arrivée dépasse le couvre-feu (déroutement, nuitée équipage...).
    curfew_penalty: float = 25000.0
    load_factor: float = 0.85
    seats: int = 180


# Couvre-feux nocturnes (heure locale). Orly : pas d'atterrissage 23h30-6h00.
CURFEWS = {"ORY": "23:30"}

# Barème EU261 : indemnisation par passager si retard à l'arrivée >= 3 h.
EU261_THRESHOLD_MIN = 180
EU261_BANDS = [(1500, 250.0), (3500, 400.0), (float("inf"), 600.0)]


def eu261_amount(distance_km: float) -> float:
    for limit, amount in EU261_BANDS:
        if distance_km <= limit:
            return amount
    return 600.0


@dataclass(frozen=True)
class ModelParams:
    test_days: int = 14
    random_state: int = 42
    xgb: dict = field(default_factory=lambda: {
        "n_estimators": 600,
        "max_depth": 6,
        "learning_rate": 0.05,
        "subsample": 0.85,
        "colsample_bytree": 0.85,
        "min_child_weight": 3,
        "reg_lambda": 1.0,
        "tree_method": "hist",
    })


OPS = OpsParams()
MODEL = ModelParams()
