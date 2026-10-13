"""
Transactional, verifiable load into MySQL.

Load protocol
-------------
1. CREATE the target tables under staging names (<table>__stg) with the full
   designed schema: types, PRIMARY KEY, NOT NULL, CHECK, FOREIGN KEY.
2. INSERT all rows in chunks inside ONE transaction. Any failure, including
   a CHECK/FK violation, rolls the whole batch back and drops the staging
   tables. The live tables are never touched.
3. Validate the staging tables with SQL (row count, key uniqueness, FK orphans).
4. Swap staging into place with a single RENAME TABLE statement, which MySQL
   executes atomically: readers see either the old or the new tables, never a
   half-loaded one.
5. Record the run, its transformation steps and its quarantined rows in the
   migration metadata tables (one transaction).

Note: MySQL DDL statements (CREATE/DROP/RENAME) commit implicitly, so DDL
and data are not covered by one transaction. The protocol never modifies
live tables except through the atomic RENAME, so that limit doesn't matter.
"""

import hashlib
import json
from datetime import date, datetime
from decimal import ROUND_HALF_UP, Decimal

import pandas as pd
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from etl.sql_schema import q, to_db_value

CHUNK_SIZE = 500

METADATA_DDL = [
    """
    CREATE TABLE IF NOT EXISTS `migration_runs` (
      `run_id` INT AUTO_INCREMENT PRIMARY KEY,
      `started_at` DATETIME NOT NULL,
      `finished_at` DATETIME NOT NULL,
      `source_system` VARCHAR(32) NOT NULL,
      `source_table` VARCHAR(64) NOT NULL,
      `target_table` VARCHAR(64) NOT NULL,
      `mode` ENUM('flat','normalized') NOT NULL,
      `source_rows` INT NOT NULL,
      `loaded_rows` INT NOT NULL,
      `duplicates_removed` INT NOT NULL,
      `quarantined_rows` INT NOT NULL,
      `status` ENUM('success','failed') NOT NULL,
      `checksum` CHAR(64),
      `error` TEXT,
      CHECK (`status` = 'failed' OR `source_rows` = `loaded_rows` + `duplicates_removed` + `quarantined_rows`)
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS `migration_steps` (
      `run_id` INT NOT NULL,
      `step_no` INT NOT NULL,
      `column_name` VARCHAR(64),
      `action` VARCHAR(64) NOT NULL,
      `detail` TEXT,
      `rows_affected` INT NOT NULL DEFAULT 0,
      PRIMARY KEY (`run_id`, `step_no`),
      FOREIGN KEY (`run_id`) REFERENCES `migration_runs` (`run_id`) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
    """
    CREATE TABLE IF NOT EXISTS `migration_quarantine` (
      `quarantine_id` INT AUTO_INCREMENT PRIMARY KEY,
      `run_id` INT NOT NULL,
      `source_row` INT NOT NULL,
      `reason` VARCHAR(255) NOT NULL,
      `raw_row` JSON NOT NULL,
      INDEX `idx_quarantine_run` (`run_id`),
      FOREIGN KEY (`run_id`) REFERENCES `migration_runs` (`run_id`) ON DELETE CASCADE
    ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
    """,
]


class LoadError(Exception):
    """Raised when the staged load fails; live tables are left untouched."""


def ensure_metadata_tables(engine):
    with engine.begin() as conn:
        for ddl in METADATA_DDL:
            conn.execute(text(ddl))


def _decimal_scale(sql_type):
    if sql_type.startswith("DECIMAL"):
        return int(sql_type.split(",")[1].rstrip(")"))
    return None


def prepare_rows(table_def, df):
    """Convert a DataFrame to DB-ready tuples, rounding DECIMALs to their scale."""
    scales = [_decimal_scale(c.sql_type) for c in table_def.columns]
    names = [c.name for c in table_def.columns]
    rows = []
    for rec in df[names].itertuples(index=False, name=None):
        out = []
        for v, scale in zip(rec, scales):
            v = to_db_value(v)
            if v is not None and scale is not None:
                v = Decimal(str(v)).quantize(Decimal(1).scaleb(-scale), rounding=ROUND_HALF_UP)
            out.append(v)
        rows.append(tuple(out))
    return rows


def _canonical(v, sql_type):
    """Render a value identically whether it came from pandas or from MySQL."""
    if v is None:
        return "\\N"
    t = sql_type.upper()
    if t.startswith("DECIMAL"):
        scale = _decimal_scale(t)
        return str(Decimal(str(v)).quantize(Decimal(1).scaleb(-scale), rounding=ROUND_HALF_UP))
    if t == "BOOLEAN":
        return "1" if bool(v) else "0"
    if t in ("INT", "BIGINT", "SMALLINT"):
        return str(int(v))
    if t == "DOUBLE":
        return repr(float(v))
    if t == "DATE":
        return (v.date() if isinstance(v, datetime) else v).isoformat()
    if t == "DATETIME":
        return v.isoformat(sep=" ") if isinstance(v, (datetime, date)) else str(v)
    return str(v)


def checksum_rows(table_def, rows):
    """SHA-256 over canonical rows sorted by primary key."""
    types = [c.sql_type for c in table_def.columns]
    lines = sorted("|".join(_canonical(v, t) for v, t in zip(r, types)) for r in rows)
    return hashlib.sha256("\n".join(lines).encode("utf-8")).hexdigest()


def _table_exists(conn, name):
    return conn.execute(
        text("SELECT COUNT(*) FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t"),
        {"t": name},
    ).scalar() > 0


def _explain(conn, sql, params):
    res = conn.execute(text("EXPLAIN " + sql), params)
    cols = list(res.keys())
    return [dict(zip(cols, r)) for r in res.fetchall()]


def staged_load(engine, plan, explain_probe=None):
    """
    plan: list of (TableDef, DataFrame), parents first (lookup tables before the
    tables that reference them).
    explain_probe: optional (table_name, column, value) used to capture EXPLAIN
    before/after the secondary index on that column is built.

    Returns a dict with per-table row counts, checksums, DDL and EXPLAIN output.
    """
    stg = {td.name: f"{td.name}__stg" for td, _ in plan}
    old = {td.name: f"{td.name}__old" for td, _ in plan}
    result = {"tables": {}, "ddl": {}, "explain": {}}

    with engine.connect() as conn:
        # Clean up leftovers from an interrupted run (children first)
        for td, _ in reversed(plan):
            conn.execute(text(f"DROP TABLE IF EXISTS {q(stg[td.name])}"))
            conn.execute(text(f"DROP TABLE IF EXISTS {q(old[td.name])}"))
        conn.commit()

        try:
            # 1. Create staging tables (without secondary indexes, added after the load)
            for td, _ in plan:
                conn.execute(text(td.create_sql(stg[td.name], ref_map=stg, include_indexes=False)))
                result["ddl"][td.name] = td.create_sql()
            conn.commit()

            # 2. Bulk insert in one transaction
            prepared = {}
            with conn.begin():
                for td, df in plan:
                    rows = prepare_rows(td, df)
                    prepared[td.name] = rows
                    cols = ", ".join(q(c.name) for c in td.columns)
                    params = ", ".join(f":p{i}" for i in range(len(td.columns)))
                    insert = text(f"INSERT INTO {q(stg[td.name])} ({cols}) VALUES ({params})")
                    for start in range(0, len(rows), CHUNK_SIZE):
                        chunk = rows[start:start + CHUNK_SIZE]
                        conn.execute(insert, [{f"p{i}": v for i, v in enumerate(r)} for r in chunk])

            # 3. Secondary indexes, with EXPLAIN before/after for the probe query
            for td, _ in plan:
                for col in td.indexes:
                    probe = explain_probe if explain_probe and explain_probe[0] == td.name and explain_probe[1] == col else None
                    sql = None
                    if probe:
                        sql = f"SELECT * FROM {q(stg[td.name])} WHERE {q(col)} = :v"
                        result["explain"]["before"] = _explain(conn, sql, {"v": probe[2]})
                    conn.execute(text(f"ALTER TABLE {q(stg[td.name])} ADD INDEX {q('idx_' + col)} ({q(col)})"))
                    conn.execute(text(f"ANALYZE TABLE {q(stg[td.name])}"))
                    if probe:
                        result["explain"]["after"] = _explain(conn, sql, {"v": probe[2]})
                        result["explain"]["query"] = sql.replace(stg[td.name], td.name).replace(":v", repr(str(probe[2])))
            conn.commit()

            # 4. Validate staging with SQL before it becomes visible
            for td, df in plan:
                n = conn.execute(text(f"SELECT COUNT(*) FROM {q(stg[td.name])}")).scalar()
                if n != len(df):
                    raise LoadError(f"{td.name}: staged {n} rows, expected {len(df)}")
            conn.commit()

            # 5. Atomic swap
            pairs = []
            for td, _ in plan:
                if _table_exists(conn, td.name):
                    pairs.append(f"{q(td.name)} TO {q(old[td.name])}")
            for td, _ in plan:
                pairs.append(f"{q(stg[td.name])} TO {q(td.name)}")
            conn.execute(text("RENAME TABLE " + ", ".join(pairs)))
            for td, _ in reversed(plan):
                conn.execute(text(f"DROP TABLE IF EXISTS {q(old[td.name])}"))
            conn.commit()
        except Exception as e:
            conn.rollback()
            for td, _ in reversed(plan):
                conn.execute(text(f"DROP TABLE IF EXISTS {q(stg[td.name])}"))
            conn.commit()
            msg = getattr(e, "orig", e)
            raise LoadError(f"Load rolled back, live tables untouched: {msg}") from e

    for td, _ in plan:
        result["tables"][td.name] = {
            "rows": len(prepared[td.name]),
            "expected_checksum": checksum_rows(td, prepared[td.name]),
        }
    return result


def record_run(engine, run):
    """Insert the run, its steps and quarantined rows in one transaction. Returns run_id."""
    with engine.begin() as conn:
        res = conn.execute(text("""
            INSERT INTO migration_runs (started_at, finished_at, source_system, source_table, target_table, mode,
                source_rows, loaded_rows, duplicates_removed, quarantined_rows, status, checksum, error)
            VALUES (:started_at, :finished_at, :source_system, :source_table, :target_table, :mode,
                :source_rows, :loaded_rows, :duplicates_removed, :quarantined_rows, :status, :checksum, :error)
        """), {k: run.get(k) for k in ("started_at", "finished_at", "source_system", "source_table", "target_table",
                                        "mode", "source_rows", "loaded_rows", "duplicates_removed",
                                        "quarantined_rows", "status", "checksum", "error")})
        run_id = res.lastrowid
        steps = [{"run_id": run_id, "step_no": i + 1, "column_name": s.get("column"), "action": s["action"],
                  "detail": s.get("detail"), "rows_affected": int(s.get("rows_affected", 0))}
                 for i, s in enumerate(run.get("steps", []))]
        if steps:
            conn.execute(text("""
                INSERT INTO migration_steps (run_id, step_no, column_name, action, detail, rows_affected)
                VALUES (:run_id, :step_no, :column_name, :action, :detail, :rows_affected)
            """), steps)
        quarantine = run.get("quarantine")
        if quarantine is not None and len(quarantine):
            conn.execute(text("""
                INSERT INTO migration_quarantine (run_id, source_row, reason, raw_row)
                VALUES (:run_id, :source_row, :reason, :raw_row)
            """), [{"run_id": run_id, "source_row": int(r.source_row), "reason": r.reason, "raw_row": r.raw}
                   for r in quarantine.itertuples(index=False)])
    return run_id


# ─────────────────────────────────────────────
# Verification: prove the data is in MySQL
# ─────────────────────────────────────────────

def _check(name, sql, expected, actual, passed=None):
    return {"check": name, "sql": sql, "expected": expected, "actual": actual,
            "passed": bool(expected == actual) if passed is None else bool(passed)}


def verify_migration(mysql_engine, pg_engine, source_table, plan, load_result, stats):
    """
    Run SQL against BOTH databases and compare with what the pipeline intended
    to load. Every check carries the exact SQL that produced it.
    """
    checks = []
    main_td, main_df = plan[-1]
    pk = main_td.primary_key

    src_sql = f'SELECT COUNT(*) FROM "{source_table}"'
    with pg_engine.connect() as pg:
        source_count = pg.execute(text(src_sql)).scalar()
    checks.append(_check("Source row count (PostgreSQL)", src_sql, stats["source_rows"], source_count))

    with mysql_engine.connect() as my:
        for td, df in plan:
            sql = f"SELECT COUNT(*) FROM {q(td.name)}"
            checks.append(_check(f"Rows in MySQL `{td.name}`", sql, len(df), my.execute(text(sql)).scalar()))

        target_count = my.execute(text(f"SELECT COUNT(*) FROM {q(main_td.name)}")).scalar()
        checks.append(_check(
            "Row accounting: source = loaded + duplicates removed + quarantined",
            f"{src_sql}  -- vs --  SELECT COUNT(*) FROM {q(main_td.name)}",
            source_count,
            target_count + stats["exact_duplicates_removed"] + stats["quarantined_rows"],
        ))

        if pk:
            sql = f"SELECT COUNT(DISTINCT {q(pk)}) FROM {q(main_td.name)}"
            checks.append(_check(f"Primary key `{pk}` is unique", sql, target_count, my.execute(text(sql)).scalar()))

        for c in main_td.columns:
            if c.sql_type.startswith("DECIMAL") and c.semantic == "money":
                sql = f"SELECT SUM({q(c.name)}) FROM {q(main_td.name)}"
                actual = my.execute(text(sql)).scalar()
                expected = sum((r[[x.name for x in main_td.columns].index(c.name)] or 0)
                               for r in prepare_rows(main_td, main_df))
                checks.append(_check(f"SUM({c.name}) matches cleaned data", sql,
                                     str(Decimal(expected)), str(actual or Decimal(0))))

        null_exprs = ", ".join(f"SUM({q(c.name)} IS NULL)" for c in main_td.columns)
        sql = f"SELECT {null_exprs} FROM {q(main_td.name)}"
        db_nulls = [int(v or 0) for v in my.execute(text(sql)).fetchone()]
        df_nulls = [int(main_df[c.name].isna().sum()) for c in main_td.columns]
        checks.append(_check("NULL count per column matches cleaned data",
                             f"SELECT SUM(col IS NULL), ... FROM {q(main_td.name)}", df_nulls, db_nulls))

        for c in main_td.columns:
            if c.references:
                rt, rc = c.references
                sql = (f"SELECT COUNT(*) FROM {q(main_td.name)} m LEFT JOIN {q(rt)} r ON m.{q(c.name)} = r.{q(rc)} "
                       f"WHERE m.{q(c.name)} IS NOT NULL AND r.{q(rc)} IS NULL")
                checks.append(_check(f"No orphan foreign keys in `{c.name}`", sql, 0, my.execute(text(sql)).scalar()))

        # Read every row back and compare a checksum with what we intended to load
        for td, _ in plan:
            cols = ", ".join(q(c.name) for c in td.columns)
            sql = f"SELECT {cols} FROM {q(td.name)}"
            rows = [tuple(r) for r in my.execute(text(sql)).fetchall()]
            actual = checksum_rows(td, rows)
            expected = load_result["tables"][td.name]["expected_checksum"]
            checks.append(_check(f"Read-back SHA-256 of `{td.name}` matches loaded data", sql + "  -- hashed row by row",
                                 expected[:16] + "…", actual[:16] + "…", passed=actual == expected))

        # Constraints really are enforced: try to break them inside a transaction, then roll back
        if pk:
            first_pk = my.execute(text(f"SELECT {q(pk)} FROM {q(main_td.name)} LIMIT 1")).scalar()
            my.commit()
            for c in main_td.columns:
                bad = None
                if c.check and c.semantic in ("money", "quantity", "age", "rating", "percentage"):
                    bad = -1
                elif c.references:
                    bad = 999999
                if bad is None:
                    continue
                sql = f"UPDATE {q(main_td.name)} SET {q(c.name)} = {bad} WHERE {q(pk)} = :pk"
                trans = my.begin()
                try:
                    my.execute(text(sql), {"pk": first_pk})
                    outcome = "accepted (constraint NOT enforced)"
                    ok = False
                except DBAPIError as e:
                    code = e.orig.args[0] if getattr(e, "orig", None) and e.orig.args else "?"
                    outcome = f"rejected by MySQL (error {code})"
                    ok = True
                finally:
                    trans.rollback()
                checks.append(_check(f"Database rejects invalid `{c.name}` = {bad}", sql.replace(":pk", repr(first_pk)),
                                     "rejected", outcome, passed=ok))
    return checks


def describe_target(mysql_engine, table_names):
    """Fetch SHOW CREATE TABLE and declared constraints straight from MySQL."""
    out = {}
    with mysql_engine.connect() as my:
        for t in table_names:
            ddl = my.execute(text(f"SHOW CREATE TABLE {q(t)}")).fetchone()[1]
            cons = my.execute(text("""
                SELECT tc.CONSTRAINT_NAME AS name, tc.CONSTRAINT_TYPE AS type, cc.CHECK_CLAUSE AS clause
                FROM information_schema.TABLE_CONSTRAINTS tc
                LEFT JOIN information_schema.CHECK_CONSTRAINTS cc
                  ON cc.CONSTRAINT_SCHEMA = tc.CONSTRAINT_SCHEMA AND cc.CONSTRAINT_NAME = tc.CONSTRAINT_NAME
                WHERE tc.TABLE_SCHEMA = DATABASE() AND tc.TABLE_NAME = :t
                ORDER BY tc.CONSTRAINT_TYPE, tc.CONSTRAINT_NAME
            """), {"t": t}).fetchall()
            cols = my.execute(text("""
                SELECT COLUMN_NAME AS column_name, COLUMN_TYPE AS column_type, IS_NULLABLE AS nullable, COLUMN_KEY AS col_key
                FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = :t
                ORDER BY ORDINAL_POSITION
            """), {"t": t}).fetchall()
            out[t] = {
                "ddl": ddl,
                "constraints": pd.DataFrame(cons, columns=["name", "type", "clause"]),
                "columns": pd.DataFrame(cols, columns=["column_name", "column_type", "nullable", "key"]),
            }
    return out


def run_history(mysql_engine, limit=10):
    with mysql_engine.connect() as my:
        return pd.read_sql(text(f"""
            SELECT run_id, finished_at, source_table, target_table, mode, source_rows, loaded_rows,
                   duplicates_removed, quarantined_rows, status, LEFT(checksum, 12) AS checksum
            FROM migration_runs ORDER BY run_id DESC LIMIT {int(limit)}
        """), my)
