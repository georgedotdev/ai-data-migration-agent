# AI Data Migration Agent: Finish-Up Tasklist

Audit: 2026-10-13. Work done on branch `finish-dbms-project`, verified against live PostgreSQL 16 and MySQL 8 (Docker).

Legend: ✅ done · 🙋 needs you

---

## P0: Immediate

- ✅ Hardcoded Railway Postgres password and `railway.internal` defaults removed from `app.py`. You confirmed that database no longer exists.
- ✅ Microsoft Visual C++ Redistributable installed (DuckDB loads now).
- ✅ venv rebuilt on Python 3.12 (`.python-version` added).
- ✅ 6 stale tests updated to match intentional API changes.
- ✅ Full suite green: **135 passed**. The 2 skips are MongoDB tests, because no MongoDB is running.
- ✅ GitHub Actions workflow runs the suite against PostgreSQL 16 and MySQL 8 service containers. It runs on your first push.

## P1: DBMS depth

- ✅ Explicit MySQL DDL from cleaned data: typed columns (`DECIMAL(12,2)`, `DATE`, `BOOLEAN`, sized `VARCHAR`), PK, NOT NULL, CHECK. Documented PG→MySQL type map.
- ✅ Transactional load: staging tables, one INSERT transaction, validation, atomic multi-table `RENAME TABLE` swap, rollback plus staging cleanup on failure. A test proves a failed load leaves the live table untouched.
- ✅ Metadata schema `migration_runs` / `migration_steps` / `migration_quarantine`, with FKs, a composite PK and a row-accounting CHECK.
- ✅ SQL reconciliation on both databases: counts, row accounting, PK uniqueness, SUMs, NULLs, FK orphans, read-back SHA-256, and constraint-enforcement probes (MySQL errors 3819 and 1452 confirmed).
- ✅ Normalization: automatic functional-dependency detection (`product → category` for orders), 3NF decomposition with FK, lossless-join test. For employees, a department reference table.
- ✅ Indexes, with EXPLAIN before/after (`ALL`, 177 rows → `ref` on `idx_join_date`, 1 row).
- ✅ Identifier validation for all interpolated table and column names. Values use bound parameters.
- ✅ Chunked inserts (500 per batch) and chunked `to_sql` in connectors.
- ✅ MySQL TLS verification restored for remote hosts (system CA, `MYSQL_SSL_CA`, or `MYSQL_SSL_CA_PEM`). Postgres `PG_SSLMODE` supported.

## P1: Data and UX

- ✅ Realistic dirty datasets from a seeded generator, with 820 injected defects listed in `data/dirty_data_manifest.json`. The UI shows them before you migrate.
- ✅ New cleaner: semantic typing, domain rules, category canonicalization, quarantine for key violations, no imputed values.
- ✅ "Proof" tab: every check shows its SQL and live result, plus `SHOW CREATE TABLE`, constraints from `information_schema`, the ER diagram, preset live queries (including a JOIN), a CSV download read from MySQL, and run history.
- ✅ API keys kept per browser session and passed per request, never written to `os.environ`. The provider list is unified.
- ✅ Retired models replaced: Groq `openai/gpt-oss-120b`, Gemini `gemini-3.8-flash`, OpenAI `gpt-4o`. Each can be overridden with `*_MODEL` env vars.
- ✅ Uploaded CSVs saved under a UUID-prefixed name, and the table name is sanitized.

## P2: Repo and docs

- ✅ `.gitignore` expanded. Runtime `.duckdb`, reports and generated outputs untracked.
- ✅ Removed `archive/`, deprecated `validation/`, root scratch scripts, empty `.md` files, duplicate CSVs, and dead `etl/load.py`. Old notes moved to `docs/dev-notes/`.
- ✅ `requirements.txt` trimmed to direct dependencies (fresh install verified). `cryptography` pinned for MySQL 8 auth.
- ✅ README rewritten.
- ✅ DBMS report: `docs/REPORT.md` (architecture, schema, normalization, ACID, indexing, verification, testing, limitations).
- ✅ `docker compose up --build` runs everything: databases, seeding, app.
- 🙋 Add fresh screenshots to the README. The old ones in `screenshots/` show the previous UI.
- 🙋 Internship check: confirm your employer is fine with you presenting this, and mention its origin if your college requires it.

## Round 2 (2026-10-14)

- ✅ Migrations between **PostgreSQL, MySQL, DuckDB, SQLite and MongoDB** in any direction (CSV upload as an extra source), with the same schema design, atomic load and verification on every engine. The 5×5 matrix is tested (50 runs, all checks pass).
- ✅ MongoDB target: `$jsonSchema` validator, unique key index, `$lookup` orphan check, staged `renameCollection`.
- ✅ Agentic (AI) tab: all engines as source/target. Fixed MongoDB target crashes and profiler blind spot for blank values.
- ✅ **Real AI verified with Gemini**: the LLM recommended 32 steps, 2 bad ones were rejected at human review, and the other 31 executed successfully into SQLite, with reconciliation passing. Fixed: the LLM schema had no `values` field, so `replace_with_null` always failed; `cast_type int64` with NULLs now uses nullable `Int64`.
- ✅ Model failover (other Gemini models, then other keyed providers, then the rule-based planner), retries capped at 2, 60-second timeout, and the real error shown in the UI.
- 🙋 Gemini's free tier often returns 503 "high demand". For a reliable demo, add a free Groq key (`GROQ_API_KEY`) as a backup, and run `RUN_LIVE_LLM=1 python -m pytest tests/test_live_llm.py -s` shortly before presenting.
- 🙋 The Gemini key was pasted into chat. Consider regenerating it in Google AI Studio after the project.

## Hosting

Recommendation: **demo locally** with `docker compose up --build`. Optional public link:

- 🙋 Create free accounts: Neon (Postgres) and Aiven (MySQL 8; avoid TiDB, which doesn't enforce CHECK by default).
- 🙋 Deploy on Streamlit Community Cloud with Python 3.12 and paste `.streamlit/secrets.toml.example` (filled in) into Secrets.
- 🙋 Run `python data/seed_postgres.py` once against Neon.

## Demo-day runbook

1. Start Docker Desktop, then run `docker compose up --build` and open http://localhost:8501.
2. HR employees → Flat → Run. Walk through the Proof tab and the constraint probes.
3. Retail orders → Normalized (3NF) → Run. Show the Schema tab: FD `product → category`, ER diagram, EXPLAIN.
4. In a terminal: `docker exec -it mysql_migration_target mysql -uroot -prootpassword migration_db`, then `SELECT * FROM migration_runs;`.
5. 🙋 Record a 3–5 minute backup video.

## Known Docker Desktop issue on this PC

If Docker Desktop crashes with "initializing Inference manager … dockerInference", rename `%LOCALAPPDATA%\Docker\run`, or turn off Docker Model Runner in Settings.
