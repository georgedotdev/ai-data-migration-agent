"""
SQL dialect differences for the migration targets and sources.

The schema designer works with canonical types (DECIMAL(12,2), DATE, BOOLEAN,
VARCHAR(n), ...) and dialect-neutral constraint rules; each dialect renders
them into its own SQL and knows how to introspect what it created.
"""

import re

from sqlalchemy import text

IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,47}$")


def safe_ident(name: str) -> str:
    """Validate a table/column identifier so it can be safely quoted into SQL."""
    if not isinstance(name, str) or not IDENT_RE.match(name):
        raise ValueError(
            f"Invalid identifier {name!r}: use letters, digits and underscores, "
            "start with a letter or underscore, max 48 characters."
        )
    return name


class Dialect:
    name = "sql"
    label = "SQL"
    quote_char = '"'
    # True: DDL is transactional, so a whole migration is one rollback-able transaction.
    # False (MySQL): DDL commits implicitly, so loads go through staging tables + RENAME.
    transactional_ddl = True
    supports_on_delete_cascade = True
    timestamp_type = "TIMESTAMP"
    json_type = "TEXT"
    type_overrides = {}

    def q(self, name: str) -> str:
        return f"{self.quote_char}{safe_ident(name)}{self.quote_char}"

    def q_raw(self, name: str) -> str:
        """Quote an arbitrary (legacy) column name, e.g. ' Employee ID '."""
        c = self.quote_char
        return c + str(name).replace(c, c + c) + c

    def map_type(self, canonical: str) -> str:
        base = canonical.split("(")[0]
        return self.type_overrides.get(base, canonical)

    def check_sql(self, rule, col: str) -> str | None:
        if not rule:
            return None
        kind, *args = rule
        c = self.q(col)
        if kind == "ge":
            return f"{c} >= {args[0]}"
        if kind == "gt":
            return f"{c} > {args[0]}"
        if kind == "between":
            return f"{c} BETWEEN {args[0]} AND {args[1]}"
        if kind == "email":
            return f"{c} LIKE '%_@_%._%'"
        if kind == "digits":
            return self.digits_check(c, args[0])
        raise ValueError(f"Unknown rule {rule}")

    def digits_check(self, c, n):
        raise NotImplementedError

    def null_count_expr(self, col):
        return f"SUM(CASE WHEN {self.q(col)} IS NULL THEN 1 ELSE 0 END)"

    def create_index_sql(self, table, index_name, col):
        return f"CREATE INDEX {self.q(index_name)} ON {self.q(table)} ({self.q(col)})"

    def table_exists(self, conn, table) -> bool:
        return conn.execute(text(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_name = :t"), {"t": table}).scalar() > 0

    def error_code(self, exc) -> str:
        orig = getattr(exc, "orig", exc)
        return type(orig).__name__

    def explain(self, conn, sql, params):
        """Return the query plan as a list of dict rows."""
        rows = conn.execute(text("EXPLAIN " + sql), params).fetchall()
        return [{"plan": str(r[0])} for r in rows]

    def explain_note(self):
        return ""

    def describe(self, conn, table):
        """Return (ddl_text or None, columns[(name, type, nullable)], constraints[(name, type, definition)])."""
        raise NotImplementedError

    def on_connect(self, dbapi_conn):
        pass


class MySQLDialect(Dialect):
    name = "mysql"
    label = "MySQL"
    quote_char = "`"
    transactional_ddl = False
    timestamp_type = "DATETIME"
    json_type = "JSON"

    def digits_check(self, c, n):
        return f"{c} REGEXP '^[0-9]{{{n}}}$'"

    def table_exists(self, conn, table):
        return conn.execute(text(
            "SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t"),
            {"t": table}).scalar() > 0

    def error_code(self, exc):
        orig = getattr(exc, "orig", None)
        if orig is not None and getattr(orig, "args", None):
            return f"MySQL error {orig.args[0]}"
        return super().error_code(exc)

    def explain(self, conn, sql, params):
        res = conn.execute(text("EXPLAIN " + sql), params)
        cols = list(res.keys())
        keep = ["type", "possible_keys", "key", "rows", "Extra"]
        return [{k: v for k, v in zip(cols, r) if k in keep} for r in res.fetchall()]

    def explain_note(self):
        return "`type=ALL` is a full table scan; `type=ref` uses the index to read only the matching rows."

    def describe(self, conn, table):
        ddl = conn.execute(text(f"SHOW CREATE TABLE {self.q(table)}")).fetchone()[1]
        cols = conn.execute(text("""
            SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t ORDER BY ORDINAL_POSITION"""), {"t": table}).fetchall()
        cons = conn.execute(text("""
            SELECT tc.CONSTRAINT_NAME, tc.CONSTRAINT_TYPE, cc.CHECK_CLAUSE
            FROM information_schema.TABLE_CONSTRAINTS tc
            LEFT JOIN information_schema.CHECK_CONSTRAINTS cc
              ON cc.CONSTRAINT_SCHEMA = tc.CONSTRAINT_SCHEMA AND cc.CONSTRAINT_NAME = tc.CONSTRAINT_NAME
            WHERE tc.TABLE_SCHEMA = DATABASE() AND tc.TABLE_NAME = :t
            ORDER BY tc.CONSTRAINT_TYPE, tc.CONSTRAINT_NAME"""), {"t": table}).fetchall()
        return ddl, [tuple(r) for r in cols], [tuple(r) for r in cons]


class PostgresDialect(Dialect):
    name = "postgresql"
    label = "PostgreSQL"
    json_type = "JSONB"
    type_overrides = {"DOUBLE": "DOUBLE PRECISION", "DATETIME": "TIMESTAMP"}

    def digits_check(self, c, n):
        return f"{c} ~ '^[0-9]{{{n}}}$'"

    def table_exists(self, conn, table):
        return conn.execute(text(
            "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = current_schema() AND table_name = :t"),
            {"t": table}).scalar() > 0

    def error_code(self, exc):
        orig = getattr(exc, "orig", None)
        code = getattr(orig, "pgcode", None)
        names = {"23514": "check_violation", "23503": "foreign_key_violation", "23502": "not_null_violation",
                 "23505": "unique_violation"}
        return f"SQLSTATE {code} {names.get(code, '')}".strip() if code else super().error_code(exc)

    def explain_note(self):
        return ("PostgreSQL's cost-based planner picks a sequential scan for a table that fits in a few pages "
                "even when an index exists; it switches to `Index Scan`/`Bitmap Index Scan` as the table grows.")

    def describe(self, conn, table):
        cols = conn.execute(text("""
            SELECT column_name,
                   data_type || COALESCE('(' || character_maximum_length || ')',
                                         CASE WHEN data_type = 'numeric' THEN '(' || numeric_precision || ',' || numeric_scale || ')' ELSE '' END),
                   is_nullable
            FROM information_schema.columns WHERE table_schema = current_schema() AND table_name = :t
            ORDER BY ordinal_position"""), {"t": table}).fetchall()
        cons = conn.execute(text("""
            SELECT conname,
                   CASE contype WHEN 'p' THEN 'PRIMARY KEY' WHEN 'f' THEN 'FOREIGN KEY' WHEN 'u' THEN 'UNIQUE'
                                WHEN 'c' THEN 'CHECK' ELSE contype::text END,
                   pg_get_constraintdef(oid)
            FROM pg_constraint WHERE conrelid = to_regclass(:t) ORDER BY contype, conname"""), {"t": table}).fetchall()
        return None, [tuple(r) for r in cols], [tuple(r) for r in cons]


class DuckDBDialect(Dialect):
    name = "duckdb"
    label = "DuckDB"
    supports_on_delete_cascade = False
    json_type = "VARCHAR"
    type_overrides = {"DATETIME": "TIMESTAMP"}

    def digits_check(self, c, n):
        return f"regexp_full_match({c}, '[0-9]{{{n}}}')"

    def table_exists(self, conn, table):
        return conn.execute(text(
            "SELECT COUNT(*) FROM duckdb_tables() WHERE table_name = :t"), {"t": table}).scalar() > 0

    def error_code(self, exc):
        orig = getattr(exc, "orig", exc)
        msg = str(orig).split("\n")[0]
        return f"{type(orig).__name__}: {msg[:90]}"

    def explain(self, conn, sql, params):
        plan = conn.execute(text("EXPLAIN " + sql), params).fetchall()[0][1]
        lines = [re.sub(r"[│─┌┐└┘┬┴├┤]+", " ", ln).strip() for ln in plan.splitlines()]
        lines = [ln for ln in lines if ln]
        out, i = [], 0
        while i < len(lines):   # keep operators, table/scan type and the (wrapped) filter text
            ln = lines[i]
            if re.fullmatch(r"[A-Z_]+", ln) and ln not in ("PROJECTION",):
                out.append({"plan": ln})
            elif ln.startswith(("Table:", "Type:")):
                out.append({"plan": ln})
            elif ln == "Filters:":
                parts = []
                while i + 1 < len(lines) and not lines[i + 1].startswith("~"):
                    i += 1
                    parts.append(lines[i])
                out.append({"plan": "Filters: " + "".join(parts)})
            i += 1
        return out

    def explain_note(self):
        return ("DuckDB is a columnar analytics engine: filters are answered with vectorized scans plus "
                "min/max zone maps, so the plan stays `SEQ_SCAN` here. Its ART indexes mainly enforce keys and "
                "speed up highly selective point lookups.")

    def describe(self, conn, table):
        ddl = conn.execute(text("SELECT sql FROM duckdb_tables() WHERE table_name = :t"), {"t": table}).scalar()
        cols = conn.execute(text("""
            SELECT column_name, data_type, is_nullable FROM information_schema.columns
            WHERE table_name = :t ORDER BY ordinal_position"""), {"t": table}).fetchall()
        cons = conn.execute(text("""
            SELECT constraint_name, constraint_type, constraint_text FROM duckdb_constraints()
            WHERE table_name = :t AND constraint_type <> 'NOT NULL' ORDER BY constraint_type"""), {"t": table}).fetchall()
        return ddl, [tuple(r) for r in cols], [tuple(r) for r in cons]


class SQLiteDialect(Dialect):
    name = "sqlite"
    label = "SQLite"
    type_overrides = {"DOUBLE": "REAL"}

    def digits_check(self, c, n):
        return f"length({c}) = {n} AND {c} NOT GLOB '*[^0-9]*'"

    def table_exists(self, conn, table):
        return conn.execute(text(
            "SELECT COUNT(*) FROM sqlite_master WHERE type = 'table' AND name = :t"), {"t": table}).scalar() > 0

    def error_code(self, exc):
        orig = getattr(exc, "orig", exc)
        return f"{type(orig).__name__}: {str(orig)[:80]}"

    def explain(self, conn, sql, params):
        rows = conn.execute(text("EXPLAIN QUERY PLAN " + sql), params).fetchall()
        return [{"plan": r[-1]} for r in rows]

    def explain_note(self):
        return "`SCAN` reads every row; `SEARCH ... USING INDEX` jumps straight to the matching rows through the B-tree."

    def describe(self, conn, table):
        ddl = conn.execute(text("SELECT sql FROM sqlite_master WHERE type = 'table' AND name = :t"), {"t": table}).scalar()
        info = conn.execute(text(f"PRAGMA table_info({self.q(table)})")).fetchall()
        cols = [(r[1], r[2], "NO" if r[3] or r[5] else "YES") for r in info]
        cons = [(f"pk_{table}", "PRIMARY KEY", ", ".join(r[1] for r in info if r[5]))] if any(r[5] for r in info) else []
        for fk in conn.execute(text(f"PRAGMA foreign_key_list({self.q(table)})")).fetchall():
            cons.append((f"fk_{fk[3]}", "FOREIGN KEY", f"({fk[3]}) REFERENCES {fk[2]}({fk[4]})"))
        for i, chk in enumerate(re.findall(r"CHECK \((.*?)\)(?:,|\n)", ddl or "")):
            cons.append((f"check_{i + 1}", "CHECK", chk))
        for idx in conn.execute(text(f"PRAGMA index_list({self.q(table)})")).fetchall():
            if idx[3] == "u":
                cons.append((idx[1], "UNIQUE", "unique index"))
        return ddl, cols, cons

    def on_connect(self, dbapi_conn):
        # Enforce foreign keys and let SQLAlchemy own transaction boundaries so DDL is transactional.
        dbapi_conn.isolation_level = None
        cur = dbapi_conn.cursor()
        cur.execute("PRAGMA foreign_keys = ON")
        cur.close()


DIALECTS = {d.name: d for d in (PostgresDialect(), MySQLDialect(), DuckDBDialect(), SQLiteDialect())}
