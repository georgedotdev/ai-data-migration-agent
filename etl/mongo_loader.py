"""
Verifiable load into MongoDB.

The relational schema design is translated into MongoDB's own integrity tools:

    NOT NULL / types / CHECK  ->  $jsonSchema validator (required, bsonType, minimum/maximum, pattern)
    PRIMARY KEY               ->  unique index on the key field
    FOREIGN KEY               ->  not enforced by MongoDB; the lookup collection is referenced
                                  by id and orphans are checked with a $lookup aggregation

Load protocol: insert into <collection>__stg (validated), check the count, then
renameCollection(..., dropTarget=True), which is atomic per collection.
"""

import json
from datetime import date, datetime
from decimal import Decimal

import pandas as pd
from bson.decimal128 import Decimal128
from pymongo.errors import PyMongoError, WriteError

from etl.sql_loader import _check, canonical, checksum_rows, prepare_rows, source_checks

BSON_TYPES = {"INT": ["int", "long"], "SMALLINT": ["int", "long"], "BIGINT": ["int", "long"], "DOUBLE": "double",
              "BOOLEAN": "bool", "DATE": "date", "DATETIME": "date", "TEXT": "string"}


def _bson_type(sql_type):
    if sql_type.startswith("DECIMAL"):
        return "decimal"
    if sql_type.startswith(("VARCHAR", "CHAR")):
        return "string"
    return BSON_TYPES.get(sql_type, "string")


def json_schema(td):
    props, required = {}, []
    for c in td.columns:
        bt = _bson_type(c.sql_type)
        bt = list(bt) if isinstance(bt, list) else [bt]
        if c.nullable:
            bt.append("null")
        p = {"bsonType": bt if len(bt) > 1 else bt[0]}
        if c.rule:
            kind, *args = c.rule
            if kind == "ge":
                p["minimum"] = args[0]
            elif kind == "gt":
                p.update(minimum=args[0], exclusiveMinimum=True)
            elif kind == "between":
                p.update(minimum=args[0], maximum=args[1])
            elif kind == "email":
                p["pattern"] = "^.+@.+\\..+$"
            elif kind == "digits":
                p["pattern"] = f"^[0-9]{{{args[0]}}}$"
        props[c.name] = p
        if not c.nullable:
            required.append(c.name)
    schema = {"bsonType": "object", "properties": props}
    if required:
        schema["required"] = required
    return {"$jsonSchema": schema}


def _to_bson(v, sql_type):
    if v is None:
        return None
    if isinstance(v, Decimal):
        return Decimal128(v)
    if isinstance(v, date) and not isinstance(v, datetime):
        return datetime(v.year, v.month, v.day)
    return v


def _from_bson(v):
    if isinstance(v, Decimal128):
        return v.to_decimal()
    return v


def _docs(td, df):
    names = [c.name for c in td.columns]
    types = [c.sql_type for c in td.columns]
    return [{n: _to_bson(v, t) for n, v, t in zip(names, row, types)} for row in prepare_rows(td, df)]


def staged_load(endpoint, plan, explain_probe=None):
    db = endpoint.mongo()
    result = {"tables": {}, "ddl": {}, "explain": {}, "protocol": (
        "MongoDB: each collection was loaded into a validated staging collection, then swapped in with "
        "renameCollection(dropTarget=True), which is atomic per collection. MongoDB does not enforce foreign "
        "keys, so references are verified with a $lookup orphan check.")}
    staged = []
    try:
        for td, df in plan:
            stg = f"{td.name}__stg"
            db.drop_collection(stg)
            db.create_collection(stg, validator=json_schema(td), validationLevel="strict", validationAction="error")
            if td.primary_key:
                db[stg].create_index(td.primary_key, unique=True, name=f"pk_{td.primary_key}")
            docs = _docs(td, df)
            if docs:
                db[stg].insert_many(docs, ordered=True)
            staged.append((td, stg))
            for col in td.indexes:
                probe = explain_probe if explain_probe and explain_probe[:2] == (td.name, col) else None
                if probe:
                    result["explain"]["before"] = _explain(db, stg, col, probe[2])
                db[stg].create_index(col, name=f"idx_{col}")
                if probe:
                    result["explain"]["after"] = _explain(db, stg, col, probe[2])
                    result["explain"]["query"] = f"db.{td.name}.find({{ {col}: ISODate('{probe[2]}') }})"
                    result["explain"]["note"] = "`COLLSCAN` reads every document; `IXSCAN` walks the B-tree index."
            if db[stg].count_documents({}) != len(df):
                raise PyMongoError(f"{td.name}: staged count mismatch")
            result["ddl"][td.name] = (
                f"db.createCollection('{td.name}', {{ validator: {json.dumps(json_schema(td), indent=2)} }})\n"
                + (f"db.{td.name}.createIndex({{ {td.primary_key}: 1 }}, {{ unique: true }})\n" if td.primary_key else "")
                + "".join(f"db.{td.name}.createIndex({{ {c}: 1 }})\n" for c in td.indexes))
        for td, stg in staged:
            db[stg].rename(td.name, dropTarget=True)
    except PyMongoError as e:
        for _, stg in staged:
            db.drop_collection(stg)
        for td, _ in plan:
            db.drop_collection(f"{td.name}__stg")
        from etl.sql_loader import LoadError
        raise LoadError(f"Load aborted, live collections untouched: {e}") from e

    for td, df in plan:
        rows = prepare_rows(td, df)
        result["tables"][td.name] = {"rows": len(rows), "expected_checksum": checksum_rows(td, rows)}
    return result


def _explain(db, coll, col, value):
    v = _to_bson(date.fromisoformat(value) if len(str(value)) == 10 else value, "DATE")
    plan_doc = db.command("explain", {"find": coll, "filter": {col: v}}, verbosity="executionStats")
    stages, node = [], plan_doc["queryPlanner"]["winningPlan"]
    while node:
        stages.append({"stage": node.get("stage"), "index": node.get("indexName", ""),
                       "docs_examined": plan_doc["executionStats"]["totalDocsExamined"]})
        node = node.get("inputStage") or node.get("queryPlan")
    return stages


def ensure_metadata_tables(endpoint):
    endpoint.mongo()["migration_runs"].create_index("run_id", unique=True)


def record_run(endpoint, run):
    coll = endpoint.mongo()["migration_runs"]
    last = coll.find_one(sort=[("run_id", -1)])
    run_id = (last["run_id"] if last else 0) + 1
    doc = {k: v for k, v in run.items() if k not in ("quarantine", "steps")}
    doc["run_id"] = run_id
    doc["steps"] = [{"step_no": i + 1, **s} for i, s in enumerate(run.get("steps", []))]
    q = run.get("quarantine")
    doc["quarantine"] = [] if q is None else [
        {"source_row": int(r.source_row), "reason": r.reason, "raw_row": json.loads(r.raw)} for r in q.itertuples(index=False)]
    coll.insert_one(doc)
    return run_id


def run_history(endpoint, limit=10):
    docs = list(endpoint.mongo()["migration_runs"].find(
        {}, {"_id": 0, "steps": 0, "quarantine": 0, "error": 0, "checksum": 0}).sort("run_id", -1).limit(limit))
    return pd.DataFrame(docs)


def verify_migration(target, source, source_table, plan, load_result, stats):
    db = target.mongo()
    main_td, main_df = plan[-1]
    pk = main_td.primary_key
    source_count, checks = source_checks(source, source_table, stats)
    t = main_td.name

    for td, df in plan:
        checks.append(_check(f"Documents in MongoDB `{td.name}`", f"db.{td.name}.countDocuments({{}})",
                             len(df), db[td.name].count_documents({})))
    target_count = db[t].count_documents({})
    checks.append(_check("Row accounting: source = loaded + duplicates removed + quarantined",
                         f"{source.count_sql(source_table)}  -- vs --  db.{t}.countDocuments({{}})", source_count,
                         target_count + stats["exact_duplicates_removed"] + stats["quarantined_rows"]))
    if pk:
        n = len(db[t].distinct(pk))
        checks.append(_check(f"Primary key `{pk}` is unique", f"db.{t}.distinct('{pk}').length", target_count, n))

    names = [c.name for c in main_td.columns]
    rows = prepare_rows(main_td, main_df)
    for c in main_td.columns:
        if c.semantic == "money":
            agg = list(db[t].aggregate([{"$group": {"_id": None, "s": {"$sum": f"${c.name}"}}}]))
            actual = _from_bson(agg[0]["s"]) if agg else 0
            expected = sum((r[names.index(c.name)] or 0) for r in rows)
            checks.append(_check(f"SUM({c.name}) matches cleaned data",
                                 f"db.{t}.aggregate([{{$group: {{_id: null, s: {{$sum: '${c.name}'}}}}}}])",
                                 canonical(expected, c.sql_type), canonical(actual, c.sql_type)))

    db_nulls = [db[t].count_documents({c.name: None}) for c in main_td.columns]
    df_nulls = [int(main_df[c.name].isna().sum()) for c in main_td.columns]
    checks.append(_check("NULL count per field matches cleaned data", f"db.{t}.countDocuments({{field: null}}) per field",
                         df_nulls, db_nulls))

    for c in main_td.columns:
        if c.references:
            rt, rc = c.references
            pipeline = [{"$match": {c.name: {"$ne": None}}},
                        {"$lookup": {"from": rt, "localField": c.name, "foreignField": rc, "as": "_ref"}},
                        {"$match": {"_ref": {"$size": 0}}}, {"$count": "n"}]
            res = list(db[t].aggregate(pipeline))
            checks.append(_check(f"No orphan references in `{c.name}` ($lookup)",
                                 f"db.{t}.aggregate([$lookup from {rt} ... $match _ref size 0])", 0, res[0]["n"] if res else 0))

    for td, _ in plan:
        docs = db[td.name].find({}, {"_id": 0})
        read = [tuple(_from_bson(doc.get(c.name)) for c in td.columns) for doc in docs]
        actual = checksum_rows(td, read)
        expected = load_result["tables"][td.name]["expected_checksum"]
        checks.append(_check(f"Read-back SHA-256 of `{td.name}` matches loaded data", f"db.{td.name}.find({{}})  -- hashed",
                             expected[:16] + "…", actual[:16] + "…", passed=actual == expected))

    if pk:
        first = db[t].find_one({}, {pk: 1})
        for c in main_td.columns:
            if not (c.rule and c.semantic in ("money", "quantity", "age", "rating", "percentage")):
                continue
            cmd = f"db.{t}.updateOne({{ {pk}: {first[pk]!r} }}, {{ $set: {{ {c.name}: -1 }} }})"
            bad = Decimal128("-1") if c.sql_type.startswith("DECIMAL") else -1
            try:
                db[t].update_one({pk: first[pk]}, {"$set": {c.name: bad}})
                outcome, ok = "accepted (validator NOT enforced)", False
                db[t].update_one({pk: first[pk]}, {"$set": {c.name: first.get(c.name)}})
            except WriteError as e:
                outcome, ok = f"rejected: Document failed validation (code {e.code})", True
            checks.append(_check(f"Validator rejects invalid `{c.name}` = -1", cmd, "rejected", outcome, passed=ok))
    return checks


def describe_target(endpoint, plan):
    db = endpoint.mongo()
    out = {}
    for td, _ in plan:
        info = db.command("listCollections", filter={"name": td.name})["cursor"]["firstBatch"]
        validator = info[0]["options"].get("validator", {}) if info else {}
        props = validator.get("$jsonSchema", {}).get("properties", {})
        required = set(validator.get("$jsonSchema", {}).get("required", []))
        keys = {td.primary_key: "PK"} if td.primary_key else {}
        keys.update({c.name: "FK" for c in td.columns if c.references})
        cols = [(n, json.dumps(p.get("bsonType")), "NO" if n in required else "YES", keys.get(n, "")) for n, p in props.items()]
        idx = [(name, "UNIQUE INDEX" if spec.get("unique") else "INDEX", json.dumps(spec["key"]))
               for name, spec in db[td.name].index_information().items()]
        rules = [(n, "VALIDATOR", json.dumps({k: v for k, v in p.items() if k != "bsonType"}))
                 for n, p in props.items() if len(p) > 1]
        out[td.name] = {
            "ddl": json.dumps(validator, indent=2, default=str),
            "ddl_source": "validator read back from listCollections",
            "columns": pd.DataFrame(cols, columns=["column_name", "column_type", "nullable", "key"]),
            "constraints": pd.DataFrame(idx + rules, columns=["name", "type", "definition"]),
        }
    return out


def live_queries(endpoint, res):
    t = res["target_table"]
    queries = {
        f"First 50 documents of `{t}`": ("find", t, {}),
        "Migration run history": ("find", "migration_runs", {}),
    }
    if res.get("lookup_table"):
        col = res["normalize_column"]
        queries[f"$lookup join with `{res['lookup_table']}` (count per {col})"] = ("aggregate", t, [
            {"$lookup": {"from": res["lookup_table"], "localField": f"{col}_id", "foreignField": "id", "as": "l"}},
            {"$unwind": "$l"}, {"$group": {"_id": f"$l.{col}", "n": {"$sum": 1}}}, {"$sort": {"n": -1}}])
    return queries


def run_query(endpoint, spec, limit=50):
    op, coll, arg = spec
    db = endpoint.mongo()
    if op == "find":
        proj = {"_id": 0, "steps": 0, "quarantine": 0} if coll == "migration_runs" else {"_id": 0}
        cursor = db[coll].find(arg, proj)
        docs = list(cursor.limit(limit) if limit else cursor)
    else:
        docs = list(db[coll].aggregate(arg))
    return pd.DataFrame([{k: (str(v) if isinstance(v, (Decimal128, dict, list)) else v) for k, v in d.items()} for d in docs])
