import os
import sys
import tempfile
from pathlib import Path

import pytest

_tmp = Path(tempfile.mkdtemp(prefix="aeroops_test_"))
os.environ["AEROOPS_DATA_DIR"] = str(_tmp / "data")
os.environ["AEROOPS_MODELS_DIR"] = str(_tmp / "models")
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp / 'data' / 'test.db'}"
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


@pytest.fixture(scope="session")
def pipeline_ready():
    from aeroops import pipeline
    pipeline.ingest_synthetic("2026-06-01", "2026-07-20", seed=1)
    pipeline.build_features()
    report = pipeline.train()
    pipeline.score(7)
    return report
