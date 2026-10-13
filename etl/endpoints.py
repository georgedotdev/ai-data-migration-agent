"""
Migration endpoints: where data is read from and written to.

    Endpoint("postgresql", {...})   Endpoint("mysql", {...})
    Endpoint("duckdb", {"path": ...})  Endpoint("sqlite", {"path": ...})
    Endpoint("mongodb", {"uri": ..., "database": ...})  Endpoint("csv", {"path": ...})  # source only

SQL endpoints expose a SQLAlchemy engine and a Dialect; MongoDB exposes a
pymongo database. All endpoints can extract a table as a DataFrame, count its
rows, and be seeded with the raw (all-text) demo data.
"""

import os
import sqlite3
from dataclasses import dataclass, field
from datetime import date, datetime

import pandas as pd
from sqlalchemy import create_engine, event, text
from sqlalchemy.pool import NullPool

from etl.dialects import DIALECTS, safe_ident

# Python 3.12 deprecated sqlite3's implicit date adapters; store ISO strings explicitly.
sqlite3.register_adapter(datetime, lambda v: v.isoformat(sep=" "))
sqlite3.register_adapter(date, lambda v: v.isoformat())

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNTIME_DIR = os.environ.get("RUNTIME_DIR", os.path.join(ROOT, "runtime"))

SQL_KINDS = ("postgresql", "mysql", "duckdb", "sqlite")
TARGET_KINDS = SQL_KINDS + ("mongodb",)
SOURCE_KINDS = TARGET_KINDS + ("csv",)
LABELS = {"postgresql": "PostgreSQL", "mysql": "MySQL", "duckdb": "DuckDB", "sqlite": "SQLite",
          "mongodb": "MongoDB", "csv": "CSV file"}


def default_config(kind, role="source"):
    """Connection defaults (env vars first, then the docker-compose values)."""
    if kind == "postgresql":
        return {"host": os.environ.get("PG_HOST", "127.0.0.1"), "port": int(os.environ.get("PG_PORT", 5432)),
                "database": os.environ.get("PG_DATABASE", "migration_db"),
                "username": os.environ.get("PG_USER", "postgres"), "password": os.environ.get("PG_PASSWORD", "")}
    if kind == "mysql":
        return {"host": os.environ.get("MYSQL_HOST", "127.0.0.1"), "port": int(os.environ.get("MYSQL_PORT", 3306)),
                "database": os.environ.get("MYSQL_DATABASE", "migration_db"),
                "username": os.environ.get("MYSQL_USER", "root"), "password": os.environ.get("MYSQL_PASSWORD", "")}
    if kind in ("duckdb", "sqlite"):
        ext = "duckdb" if kind == "duckdb" else "sqlite"
        return {"path": os.path.join(RUNTIME_DIR, f"{role}.{ext}")}
    if kind == "mongodb":
        return {"uri": os.environ.get("MONGO_URI", "mongodb://127.0.0.1:27017"),
                "database": os.environ.get("MONGO_DATABASE", "migration_db")}
    return {}


@dataclass
class Endpoint:
    kind: str
    config: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.kind not in SOURCE_KINDS:
            raise ValueError(f"Unsupported endpoint kind {self.kind!r}")
        self._engine = None
        self._mongo = None

    @property
    def label(self):
        return LABELS[self.kind]

    @property
    def is_sql(self):
        return self.kind in SQL_KINDS

    @property
    def dialect(self):
        return DIALECTS[self.kind]

    def describe_location(self):
        c = self.config
        if self.kind in ("duckdb", "sqlite", "csv"):
            return c.get("path", "")
        if self.kind == "mongodb":
            return f"{c.get('uri', '').split('@')[-1]} / {c.get('database')}"
        return f"{c.get('host')}:{c.get('port')}/{c.get('database')}"

    # ── connections ──────────────────────────────────────────
    def engine(self):
        if self._engine is not None:
            return self._engine
        if self.kind == "postgresql":
            from connectors.postgres_connector import PostgreSQLConnector
            self._engine = PostgreSQLConnector(**self.config).engine
        elif self.kind == "mysql":
            from connectors.mysql_connector import MySQLConnector
            self._engine = MySQLConnector(**self.config).engine
        elif self.kind == "duckdb":
            path = self.config["path"]
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            self._engine = create_engine(f"duckdb:///{path}", poolclass=NullPool)
        elif self.kind == "sqlite":
            path = self.config["path"]
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            eng = create_engine(f"sqlite:///{path}", poolclass=NullPool)
            dialect = self.dialect

            @event.listens_for(eng, "connect")
            def _on_connect(dbapi_conn, _rec):
                dialect.on_connect(dbapi_conn)

            @event.listens_for(eng, "begin")
            def _on_begin(conn):
                conn.exec_driver_sql("BEGIN")

            self._engine = eng
        else:
            raise ValueError(f"{self.kind} has no SQL engine")
        return self._engine

    def mongo(self):
        if self._mongo is None:
            from pymongo import MongoClient
            client = MongoClient(self.config["uri"], serverSelectionTimeoutMS=4000)
            self._mongo = client[self.config["database"]]
        return self._mongo

    def ping(self):
        if self.is_sql:
            with self.engine().connect() as c:
                return str(c.execute(text({"postgresql": "SELECT version()", "mysql": "SELECT CONCAT('MySQL ', VERSION())",
                                           "duckdb": "SELECT 'DuckDB ' || version()",
                                           "sqlite": "SELECT 'SQLite ' || sqlite_version()"}[self.kind])).scalar()).split(",")[0]
        if self.kind == "mongodb":
            return "MongoDB " + self.mongo().client.server_info()["version"]
        return "CSV " + ("found" if os.path.exists(self.config.get("path", "")) else "missing")

    # ── reading ──────────────────────────────────────────────
    def read_table(self, table) -> pd.DataFrame:
        if self.kind == "csv":
            return pd.read_csv(self.config["path"], dtype=str, keep_default_na=False)
        if self.kind == "mongodb":
            docs = list(self.mongo()[safe_ident(table)].find({}, {"_id": 0}))
            return pd.DataFrame(docs)
        with self.engine().connect() as c:
            return pd.read_sql(text(f"SELECT * FROM {self.dialect.q(table)}"), c)

    def count_sql(self, table):
        if self.kind == "csv":
            return f"-- rows in {os.path.basename(self.config['path'])} (pandas)"
        if self.kind == "mongodb":
            return f"db.{table}.countDocuments({{}})"
        return f"SELECT COUNT(*) FROM {self.dialect.q(table)}"

    def count(self, table) -> int:
        if self.kind == "csv":
            return len(self.read_table(table))
        if self.kind == "mongodb":
            return self.mongo()[safe_ident(table)].count_documents({})
        with self.engine().connect() as c:
            return c.execute(text(self.count_sql(table))).scalar()

    def column_types(self, table) -> dict:
        """Source column -> declared type (for the type-mapping table)."""
        if self.kind == "csv":
            return {}
        if self.kind == "mongodb":
            doc = self.mongo()[safe_ident(table)].find_one({}, {"_id": 0}) or {}
            return {k: type(v).__name__ for k, v in doc.items()}
        with self.engine().connect() as c:
            if self.kind == "sqlite":
                rows = c.execute(text(f"PRAGMA table_info({self.dialect.q(table)})")).fetchall()
                return {r[1]: r[2] for r in rows}
            schema_filter = {"postgresql": "table_schema = current_schema() AND ",
                             "mysql": "table_schema = DATABASE() AND "}.get(self.kind, "")
            rows = c.execute(text(f"SELECT column_name, data_type FROM information_schema.columns "
                                  f"WHERE {schema_filter}table_name = :t"), {"t": table}).fetchall()
            return {r[0]: r[1] for r in rows}

    def list_tables(self):
        if self.kind == "mongodb":
            return sorted(n for n in self.mongo().list_collection_names() if not n.startswith("system."))
        if self.kind == "csv":
            return []
        with self.engine().connect() as c:
            sql = {"postgresql": "SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema() AND table_type = 'BASE TABLE'",
                   "mysql": "SELECT table_name FROM information_schema.tables WHERE table_schema = DATABASE()",
                   "duckdb": "SELECT table_name FROM duckdb_tables()",
                   "sqlite": "SELECT name FROM sqlite_master WHERE type = 'table'"}[self.kind]
            return sorted(r[0] for r in c.execute(text(sql)))

    # ── seeding raw legacy data ──────────────────────────────
    def seed_raw(self, table, df: pd.DataFrame) -> int:
        """Store df as a legacy table: every column text, original header names, blanks as ''."""
        safe_ident(table)
        df = df.astype(str)
        if self.kind == "mongodb":
            coll = self.mongo()[table]
            coll.drop()
            coll.insert_many(df.to_dict("records"))
            return len(df)
        if self.kind == "csv":
            raise ValueError("CSV endpoints are read-only")
        d = self.dialect
        if self.kind == "mysql":   # MySQL rejects column names with trailing spaces
            df = df.rename(columns=lambda c: str(c).rstrip())
        text_type = "LONGTEXT" if self.kind == "mysql" else "TEXT"
        cols = ", ".join(f"{d.q_raw(c)} {text_type}" for c in df.columns)
        placeholders = ", ".join(f":c{i}" for i in range(len(df.columns)))
        rows = [{f"c{i}": v for i, v in enumerate(r)} for r in df.itertuples(index=False, name=None)]
        with self.engine().begin() as conn:
            conn.execute(text(f"DROP TABLE IF EXISTS {d.q(table)}"))
            conn.execute(text(f"CREATE TABLE {d.q(table)} ({cols})"))
            conn.execute(text(f"INSERT INTO {d.q(table)} VALUES ({placeholders})"), rows)
        return len(df)

    def dispose(self):
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None
        if self._mongo is not None:
            self._mongo.client.close()
            self._mongo = None
