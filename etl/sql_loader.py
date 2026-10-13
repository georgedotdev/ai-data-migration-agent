"""
Transactional, verifiable load into a SQL target (PostgreSQL, MySQL, DuckDB, SQLite).

Two load protocols, chosen by whether the engine has transactional DDL:

PostgreSQL / DuckDB / SQLite (transactional DDL)
    One transaction does everything: DROP the old tables, CREATE the new ones
    with all constraints, INSERT in chunks, build indexes, validate. COMMIT
    makes the new tables visible at once; any error rolls the whole thing back,
    including the DROPs, so the old tables come back untouched.

MySQL (DDL commits implicitly)
    CREATE <table>__stg tables, INSERT in one transaction, validate, then swap
    with a single multi-table RENAME TABLE statement, which MySQL executes
    atomically. A failure drops the staging tables; live tables are untouched.

After loading, every run (steps and quarantined rows included) is recorded in
metadata tables in the target database.
"""

import hashlib
import json
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

import pandas as pd
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from etl.sql_schema import index_name, to_db_value

CHUNK_SIZE = 500


class LoadError(Exception):
    """Raised when a load fails; live tables are left untouched."""


# ─────────────────────────────────────────────
# Metadata tables
# ─────────────────────────────────────────────

def metadata_ddl(d):
    ts, js = d.timestamp_type, d.json_type
    cascade = " ON DELETE CASCADE" if d.supports_on_delete_cascade else ""
    return [
        f"""CREATE TABLE IF NOT EXISTS {d.q('migration_runs')} (
          {d.q('run_id')} INT PRIMARY KEY,
          {d.q('started_at')} {ts} NOT NULL,
          {d.q('finished_at')} {ts} NOT NULL,
          {d.q('source_system')} VARCHAR(32) NOT NULL,
          {d.q('source_table')} VARCHAR(64) NOT NULL,
          {d.q('target_system')} VARCHAR(32) NOT NULL,
          {d.q('target_table')} VARCHAR(64) NOT NULL,
          {d.q('mode')} VARCHAR(16) NOT NULL CHECK ({d.q('mode')} IN ('flat', 'normalized')),
          {d.q('source_rows')} INT NOT NULL,
          {d.q('loaded_rows')} INT NOT NULL,
          {d.q('duplicates_removed')} INT NOT NULL,
          {d.q('quarantined_rows')} INT NOT NULL,
          {d.q('status')} VARCHAR(16) NOT NULL CHECK ({d.q('status')} IN ('success', 'failed')),
          {d.q('checksum')} CHAR(64),
          {d.q('error')} TEXT,
          CHECK ({d.q('status')} = 'failed' OR {d.q('source_rows')} = {d.q('loaded_rows')} + {d.q('duplicates_removed')} + {d.q('quarantined_rows')})
        )""",
        f"""CREATE TABLE IF NOT EXISTS {d.q('migration_steps')} (
          {d.q('run_id')} INT NOT NULL,
          {d.q('step_no')} INT NOT NULL,
          {d.q('column_name')} VARCHAR(64),
          {d.q('action')} VARCHAR(64) NOT NULL,
          {d.q('detail')} TEXT,
          {d.q('rows_affected')} INT NOT NULL DEFAULT 0,
          PRIMARY KEY ({d.q('run_id')}, {d.q('step_no')}),
          FOREIGN KEY ({d.q('run_id')}) REFERENCES {d.q('migration_runs')} ({d.q('run_id')}){cascade}
        )""",
        f"""CREATE TABLE IF NOT EXISTS {d.q('migration_quarantine')} (
          {d.q('run_id')} INT NOT NULL,
          {d.q('source_row')} INT NOT NULL,
          {d.q('reason')} VARCHAR(255) NOT NULL,
          {d.q('raw_row')} {js} NOT NULL,
          PRIMARY KEY ({d.q('run_id')}, {d.q('source_row')}),
          FOREIGN KEY ({d.q('run_id')}) REFERENCES {d.q('migration_runs')} ({d.q('run_id')}){cascade}
        )""",
    ]


def ensure_metadata_tables(endpoint):
    d = endpoint.dialect
    with endpoint.engine().begin() as conn:
        for ddl in metadata_ddl(d):
            conn.execute(text(ddl))
    _upgrade_legacy_metadata(endpoint)


def _upgrade_legacy_metadata(endpoint):
    """Earlier MySQL-only versions had no target_system column and auto-increment ids."""
    if endpoint.kind != "mysql":
        return
    with endpoint.engine().begin() as conn:
        has = conn.execute(text("""SELECT COUNT(*) FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE()
                                   AND TABLE_NAME = 'migration_runs' AND COLUMN_NAME = 'target_system'""")).scalar()
        if not has:
            conn.execute(text("ALTER TABLE `migration_runs` ADD COLUMN `target_system` VARCHAR(32) NOT NULL DEFAULT 'mysql' AFTER `source_table`"))


# ─────────────────────────────────────────────
# Values and checksums
# ─────────────────────────────────────────────

def _decimal_scale(sql_type):
    if sql_type.startswith("DECIMAL"):
        return int(sql_type.split(",")[1].rstrip(")"))
    return None


def prepare_rows(table_def, df, dialect=None):
    """Convert a DataFrame to DB-ready tuples (DECIMALs rounded to scale, DATEs as dates)."""
    kinds = [c.sql_type for c in table_def.columns]
    scales = [_decimal_scale(t) for t in kinds]
    names = [c.name for c in table_def.columns]
    sqlite = dialect is not None and dialect.name == "sqlite"
    rows = []
    for rec in df[names].itertuples(index=False, name=None):
        out = []
        for v, scale, t in zip(rec, scales, kinds):
            v = to_db_value(v)
            if v is not None:
                if scale is not None:
                    v = Decimal(str(v)).quantize(Decimal(1).scaleb(-scale), rounding=ROUND_HALF_UP)
                    if sqlite:
                        v = float(v)
                elif t == "DATE" and isinstance(v, datetime):
                    v = v.date()
                if sqlite and isinstance(v, (date, datetime)):
                    v = v.isoformat(sep=" ") if isinstance(v, datetime) else v.isoformat()
            out.append(v)
        rows.append(tuple(out))
    return rows


def canonical(v, sql_type):
    """Render a value identically whether it came from pandas or from any database."""
    if v is None:
        return "\\N"
    t = sql_type.upper()
    if t.startswith("DECIMAL"):
        scale = _decimal_scale(t)
        return str(Decimal(str(v)).quantize(Decimal(1).scaleb(-scale), rounding=ROUND_HALF_UP))
    if t == "BOOLEAN":
        return "1" if (v.lower() in ("1", "true") if isinstance(v, str) else bool(v)) else "0"
    if t in ("INT", "BIGINT", "SMALLINT"):
        return str(int(v))
    if t == "DOUBLE":
        return repr(float(v))
    if t == "DATE":
        if isinstance(v, str):
            return v[:10]
        return (v.date() if isinstance(v, datetime) else v).isoformat()
    if t == "DATETIME":
        if isinstance(v, str):
            return v.replace("T", " ")[:19]
        return v.isoformat(sep=" ")[:19] if isinstance(v, (datetime, date)) else str(v)
    return str(v)


def checksum_rows(table_def, rows):
    """SHA-256 over canonical rows (order-independent)."""
    types = [c.sql_type for c in table_def.columns]
    lines = sorted("|".join(canonical(v, t) for v, t in zip(r, types)) for r in rows)
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


# ─────────────────────────────────────────────
# Load
# ─────────────────────────────────────────────

def _insert(conn, d, td, physical, rows):
    cols = ", ".join(d.q(c.name) for c in td.columns)
    params = ", ".join(f":p{i}" for i in range(len(td.columns)))
    insert = text(f"INSERT INTO {d.q(physical)} ({cols}) VALUES ({params})")
    for start in range(0, len(rows), CHUNK_SIZE):
        chunk = rows[start:start + CHUNK_SIZE]
        conn.execute(insert, [{f"p{i}": v for i, v in enumerate(r)} for r in chunk])


def _indexes_with_explain(conn, d, td, physical, probe, result):
    for col in td.indexes:
        sql = None
        if probe and probe[0] == td.name and probe[1] == col:
            sql = f"SELECT * FROM {d.q(physical)} WHERE {d.q(col)} = :v"
            result["explain"]["before"] = d.explain(conn, sql, {"v": probe[2]})
        conn.execute(text(d.create_index_sql(physical, index_name(td.name, col), col)))
        if d.name == "mysql":
            conn.execute(text(f"ANALYZE TABLE {d.q(physical)}"))
        elif d.name in ("postgresql", "sqlite"):
            conn.execute(text(f"ANALYZE {d.q(physical)}"))
        if sql:
            result["explain"]["after"] = d.explain(conn, sql, {"v": probe[2]})
            result["explain"]["query"] = sql.replace(d.q(physical), d.q(td.name)).replace(":v", repr(str(probe[2])))
            result["explain"]["note"] = d.explain_note()


def staged_load(endpoint, plan, explain_probe=None):
    """
    plan: list of (TableDef, DataFrame), parents first (lookup tables before the
    tables that reference them).
    explain_probe: optional (table, column, value) to capture EXPLAIN before/after
    the secondary index on that column is built.
    """
    d = endpoint.dialect
    result = {"tables": {}, "ddl": {}, "explain": {}, "protocol": None}
    prepared = {td.name: prepare_rows(td, df, d) for td, df in plan}
    for td, _ in plan:
        result["ddl"][td.name] = td.create_sql(dialect=d) + (
            ";\n" + ";\n".join(td.index_sql(d)) if td.indexes and d.name != "mysql" else "")

    if d.transactional_ddl:
        result["protocol"] = (f"{d.label} has transactional DDL: DROP + CREATE + INSERT + CREATE INDEX ran in ONE "
                              "transaction, so the switch to the new tables happened atomically at COMMIT.")
        try:
            with endpoint.engine().connect() as conn:
                with conn.begin():
                    for td, _ in reversed(plan):
                        conn.execute(text(f"DROP TABLE IF EXISTS {d.q(td.name)}"))
                    for td, _ in plan:
                        conn.execute(text(td.create_sql(dialect=d)))
                    for td, _ in plan:
                        _insert(conn, d, td, td.name, prepared[td.name])
                    for td, _ in plan:
                        _indexes_with_explain(conn, d, td, td.name, explain_probe, result)
                    for td, df in plan:
                        n = conn.execute(text(f"SELECT COUNT(*) FROM {d.q(td.name)}")).scalar()
                        if n != len(df):
                            raise LoadError(f"{td.name}: loaded {n} rows, expected {len(df)}")
        except Exception as e:
            msg = getattr(e, "orig", e)
            raise LoadError(f"Load rolled back, live tables untouched: {msg}") from e
    else:
        result["protocol"] = ("MySQL commits DDL implicitly, so rows were loaded into staging tables in one "
                              "transaction and swapped in with a single atomic RENAME TABLE statement.")
        _mysql_staged_load(endpoint, plan, prepared, explain_probe, result)

    for td, _ in plan:
        result["tables"][td.name] = {"rows": len(prepared[td.name]),
                                     "expected_checksum": checksum_rows(td, prepared[td.name])}
    return result


def _mysql_staged_load(endpoint, plan, prepared, explain_probe, result):
    d = endpoint.dialect
    stg = {td.name: f"{td.name}__stg" for td, _ in plan}
    old = {td.name: f"{td.name}__old" for td, _ in plan}
    with endpoint.engine().connect() as conn:
        for td, _ in reversed(plan):
            conn.execute(text(f"DROP TABLE IF EXISTS {d.q(stg[td.name])}"))
            conn.execute(text(f"DROP TABLE IF EXISTS {d.q(old[td.name])}"))
        conn.commit()
        try:
            for td, _ in plan:
                conn.execute(text(td.create_sql(stg[td.name], ref_map=stg, include_indexes=False, dialect=d)))
            conn.commit()
            with conn.begin():
                for td, _ in plan:
                    _insert(conn, d, td, stg[td.name], prepared[td.name])
            for td, _ in plan:
                _indexes_with_explain(conn, d, td, stg[td.name], explain_probe, result)
            conn.commit()
            for td, df in plan:
                n = conn.execute(text(f"SELECT COUNT(*) FROM {d.q(stg[td.name])}")).scalar()
                if n != len(df):
                    raise LoadError(f"{td.name}: staged {n} rows, expected {len(df)}")
            conn.commit()
            pairs = [f"{d.q(td.name)} TO {d.q(old[td.name])}" for td, _ in plan if d.table_exists(conn, td.name)]
            pairs += [f"{d.q(stg[td.name])} TO {d.q(td.name)}" for td, _ in plan]
            conn.execute(text("RENAME TABLE " + ", ".join(pairs)))
            for td, _ in reversed(plan):
                conn.execute(text(f"DROP TABLE IF EXISTS {d.q(old[td.name])}"))
            conn.commit()
        except Exception as e:
            conn.rollback()
            for td, _ in reversed(plan):
                conn.execute(text(f"DROP TABLE IF EXISTS {d.q(stg[td.name])}"))
            conn.commit()
            raise LoadError(f"Load rolled back, live tables untouched: {getattr(e, 'orig', e)}") from e


# ─────────────────────────────────────────────
# Run metadata
# ─────────────────────────────────────────────

def record_run(endpoint, run):
    """Insert the run, its steps and quarantined rows in one transaction. Returns run_id."""
    d = endpoint.dialect
    cols = ["run_id", "started_at", "finished_at", "source_system", "source_table", "target_system", "target_table",
            "mode", "source_rows", "loaded_rows", "duplicates_removed", "quarantined_rows", "status", "checksum", "error"]
    with endpoint.engine().begin() as conn:
        run_id = conn.execute(text(f"SELECT COALESCE(MAX({d.q('run_id')}), 0) + 1 FROM {d.q('migration_runs')}")).scalar()
        params = {k: run.get(k) for k in cols}
        params["run_id"] = int(run_id)
        conn.execute(text(f"INSERT INTO {d.q('migration_runs')} ({', '.join(d.q(c) for c in cols)}) "
                          f"VALUES ({', '.join(':' + c for c in cols)})"), params)
        steps = [{"run_id": run_id, "step_no": i + 1, "column_name": s.get("column"), "action": s["action"],
                  "detail": s.get("detail"), "rows_affected": int(s.get("rows_affected", 0))}
                 for i, s in enumerate(run.get("steps", []))]
        if steps:
            conn.execute(text(f"INSERT INTO {d.q('migration_steps')} (run_id, step_no, column_name, action, detail, rows_affected) "
                              "VALUES (:run_id, :step_no, :column_name, :action, :detail, :rows_affected)"), steps)
        quarantine = run.get("quarantine")
        if quarantine is not None and len(quarantine):
            conn.execute(text(f"INSERT INTO {d.q('migration_quarantine')} (run_id, source_row, reason, raw_row) "
                              "VALUES (:run_id, :source_row, :reason, :raw_row)"),
                         [{"run_id": run_id, "source_row": int(r.source_row), "reason": r.reason, "raw_row": r.raw}
                          for r in quarantine.itertuples(index=False)])
    return int(run_id)


def run_history(endpoint, limit=10):
    d = endpoint.dialect
    with endpoint.engine().connect() as conn:
        return pd.read_sql(text(f"""
            SELECT run_id, finished_at, source_system, source_table, target_system, target_table, mode,
                   source_rows, loaded_rows, duplicates_removed, quarantined_rows, status
            FROM {d.q('migration_runs')} ORDER BY run_id DESC LIMIT {int(limit)}"""), conn)


# ─────────────────────────────────────────────
# Verification
# ─────────────────────────────────────────────

def _check(name, sql, expected, actual, passed=None):
    return {"check": name, "sql": sql, "expected": expected, "actual": actual,
            "passed": bool(expected == actual) if passed is None else bool(passed)}


def source_checks(source, source_table, stats):
    sql = source.count_sql(source_table)
    n = source.count(source_table)
    return n, [_check(f"Source row count ({source.label})", sql, stats["source_rows"], n)]


def verify_migration(target, source, source_table, plan, load_result, stats):
    """Run queries against both systems and compare with what the pipeline loaded."""
    d = target.dialect
    main_td, main_df = plan[-1]
    pk = main_td.primary_key
    source_count, checks = source_checks(source, source_table, stats)
    t = d.q(main_td.name)

    with target.engine().connect() as conn:
        for td, df in plan:
            sql = f"SELECT COUNT(*) FROM {d.q(td.name)}"
            checks.append(_check(f"Rows in {target.label} `{td.name}`", sql, len(df), conn.execute(text(sql)).scalar()))
        target_count = conn.execute(text(f"SELECT COUNT(*) FROM {t}")).scalar()
        checks.append(_check("Row accounting: source = loaded + duplicates removed + quarantined",
                             f"{source.count_sql(source_table)}  -- vs --  SELECT COUNT(*) FROM {t}", source_count,
                             target_count + stats["exact_duplicates_removed"] + stats["quarantined_rows"]))
        if pk:
            sql = f"SELECT COUNT(DISTINCT {d.q(pk)}) FROM {t}"
            checks.append(_check(f"Primary key `{pk}` is unique", sql, target_count, conn.execute(text(sql)).scalar()))

        names = [c.name for c in main_td.columns]
        rows = prepare_rows(main_td, main_df)
        for c in main_td.columns:
            if c.semantic == "money":
                sql = f"SELECT SUM({d.q(c.name)}) FROM {t}"
                actual = conn.execute(text(sql)).scalar()
                expected = sum((r[names.index(c.name)] or 0) for r in rows)
                checks.append(_check(f"SUM({c.name}) matches cleaned data", sql,
                                     canonical(expected, c.sql_type), canonical(actual or 0, c.sql_type)))

        sql = f"SELECT {', '.join(d.null_count_expr(c.name) for c in main_td.columns)} FROM {t}"
        db_nulls = [int(v or 0) for v in conn.execute(text(sql)).fetchone()]
        df_nulls = [int(main_df[c.name].isna().sum()) for c in main_td.columns]
        checks.append(_check("NULL count per column matches cleaned data",
                             f"SELECT SUM(CASE WHEN col IS NULL THEN 1 ELSE 0 END), ... FROM {t}", df_nulls, db_nulls))

        for c in main_td.columns:
            if c.references:
                rt, rc = c.references
                sql = (f"SELECT COUNT(*) FROM {t} m LEFT JOIN {d.q(rt)} r ON m.{d.q(c.name)} = r.{d.q(rc)} "
                       f"WHERE m.{d.q(c.name)} IS NOT NULL AND r.{d.q(rc)} IS NULL")
                checks.append(_check(f"No orphan foreign keys in `{c.name}`", sql, 0, conn.execute(text(sql)).scalar()))

        for td, _ in plan:
            sql = f"SELECT {', '.join(d.q(c.name) for c in td.columns)} FROM {d.q(td.name)}"
            actual = checksum_rows(td, [tuple(r) for r in conn.execute(text(sql)).fetchall()])
            expected = load_result["tables"][td.name]["expected_checksum"]
            checks.append(_check(f"Read-back SHA-256 of `{td.name}` matches loaded data", sql + "  -- hashed row by row",
                                 expected[:16] + "…", actual[:16] + "…", passed=actual == expected))

        if pk:
            first_pk = conn.execute(text(f"SELECT {d.q(pk)} FROM {t} LIMIT 1")).scalar()
            conn.commit()
            for c in main_td.columns:
                bad = -1 if (c.rule and c.semantic in ("money", "quantity", "age", "rating", "percentage")) else (
                    999999 if c.references else None)
                if bad is None:
                    continue
                sql = f"UPDATE {t} SET {d.q(c.name)} = {bad} WHERE {d.q(pk)} = :pk"
                trans = conn.begin()
                try:
                    conn.execute(text(sql), {"pk": first_pk})
                    outcome, ok = "accepted (constraint NOT enforced)", False
                except DBAPIError as e:
                    outcome, ok = f"rejected: {d.error_code(e)}", True
                finally:
                    trans.rollback()
                checks.append(_check(f"Database rejects invalid `{c.name}` = {bad}",
                                     sql.replace(":pk", repr(first_pk)), "rejected", outcome, passed=ok))
    return checks


def describe_target(endpoint, plan):
    """Columns, constraints and DDL as reported by the target database itself."""
    d = endpoint.dialect
    out = {}
    with endpoint.engine().connect() as conn:
        for td, _ in plan:
            ddl, cols, cons = d.describe(conn, td.name)
            keys = {td.primary_key: "PK"} if td.primary_key else {}
            keys.update({c.name: "FK" for c in td.columns if c.references})
            out[td.name] = {
                "ddl": ddl or td.create_sql(dialect=d),
                "ddl_source": "from the database catalog" if ddl else "as executed (rebuilt from the plan)",
                "columns": pd.DataFrame([(n, t, nl, keys.get(n, "")) for n, t, nl in cols],
                                        columns=["column_name", "column_type", "nullable", "key"]),
                "constraints": pd.DataFrame(cons, columns=["name", "type", "definition"]),
            }
    return out


def live_queries(endpoint, res):
    """Preset read-only queries the UI can run against the target."""
    d = endpoint.dialect
    t = d.q(res["target_table"])
    queries = {
        f"First 50 rows of `{res['target_table']}`": f"SELECT * FROM {t} LIMIT 50",
        "Migration run history (metadata table)": f"SELECT * FROM {d.q('migration_runs')} ORDER BY run_id DESC LIMIT 20",
        "Transformation steps of this run": f"SELECT step_no, column_name, action, rows_affected, detail FROM {d.q('migration_steps')} WHERE run_id = {int(res['run_id'])} ORDER BY step_no",
        "Quarantined rows of this run": f"SELECT source_row, reason, raw_row FROM {d.q('migration_quarantine')} WHERE run_id = {int(res['run_id'])}",
    }
    if res.get("lookup_table"):
        lk, col = d.q(res["lookup_table"]), res["normalize_column"]
        money = next((r.target_column for r in res["type_mapping"].itertuples()
                      if r.detected_as == "money" and r.target_table == res["target_table"]), None)
        agg = f", ROUND(AVG(m.{d.q(money)}), 2) AS avg_{money}" if money else ""
        queries[f"JOIN with `{res['lookup_table']}` (aggregate per {col})"] = (
            f"SELECT l.{d.q(col)}, COUNT(*) AS n{agg} FROM {t} m JOIN {lk} l ON m.{d.q(col + '_id')} = l.{d.q('id')} "
            f"GROUP BY l.{d.q(col)} ORDER BY n DESC")
    return queries


def run_query(endpoint, sql):
    with endpoint.engine().connect() as conn:
        return pd.read_sql(text(sql), conn)


def quarantine_json(raw):
    return raw if isinstance(raw, str) else json.dumps(raw)
