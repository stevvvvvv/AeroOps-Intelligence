"""Accès base de données (SQLite en local, PostgreSQL en conteneur)."""
from __future__ import annotations

from datetime import date, datetime
from functools import lru_cache

import pandas as pd
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

from .config import DATA_DIR, DATABASE_URL, ROOT


@lru_cache(maxsize=4)
def get_engine(url: str = DATABASE_URL) -> Engine:
    if url.startswith("sqlite"):
        DATA_DIR.mkdir(parents=True, exist_ok=True)
    return create_engine(url, future=True)


def init_db(engine: Engine | None = None) -> None:
    engine = engine or get_engine()
    ddl = (ROOT / "sql" / "schema.sql").read_text(encoding="utf-8")
    with engine.begin() as conn:
        for chunk in ddl.split(";"):
            stmt = "\n".join(l.split("--")[0] for l in chunk.splitlines()).strip()
            if stmt:
                conn.execute(text(stmt))


def replace_rows(df: pd.DataFrame, table: str, engine: Engine | None = None,
                 where: str | None = None, params: dict | None = None) -> int:
    """Supprime puis insère (conserve le schéma et les contraintes de schema.sql)."""
    engine = engine or get_engine()
    with engine.begin() as conn:
        conn.execute(text(f"DELETE FROM {table}" + (f" WHERE {where}" if where else "")), params or {})
        df.to_sql(table, conn, if_exists="append", index=False, chunksize=max(1, 30000 // max(len(df.columns), 1)), method="multi")
    return len(df)


def read_sql(query: str, params: dict | None = None, engine: Engine | None = None,
             parse_dates: list[str] | None = None) -> pd.DataFrame:
    engine = engine or get_engine()
    # dates passées en ISO : fonctionne à l'identique sous SQLite et PostgreSQL
    params = {k: (v.isoformat() if isinstance(v, (date, datetime)) else v) for k, v in (params or {}).items()}
    with engine.connect() as conn:
        return pd.read_sql(text(query), conn, params=params or {}, parse_dates=parse_dates)


def load_named_queries(path: str = "sql/kpis.sql") -> dict[str, str]:
    """Charge les requêtes nommées d'un fichier SQL (blocs '-- name: xxx')."""
    queries: dict[str, str] = {}
    current, buf = None, []
    for line in (ROOT / path).read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("-- name:"):
            if current:
                queries[current] = "\n".join(buf).strip().rstrip(";")
            current, buf = line.split(":", 1)[1].strip(), []
        elif current:
            buf.append(line)
    if current:
        queries[current] = "\n".join(buf).strip().rstrip(";")
    return queries
