"""
Target schema design.

Instead of letting pandas.to_sql guess column types, the migration derives an
explicit schema from the cleaned data and its semantic types: data types,
PRIMARY KEY, NOT NULL, CHECK, UNIQUE and FOREIGN KEY constraints. Types and
rules are canonical; each dialect (etl/dialects.py) renders them, and the
MongoDB loader turns them into a $jsonSchema validator.
"""

import math
from dataclasses import dataclass, field

import pandas as pd

from etl.dialects import DIALECTS, safe_ident  # noqa: F401  (safe_ident re-exported)

# Reference mapping used when a PostgreSQL source column is already typed.
PG_TO_MYSQL = {
    "smallint": "SMALLINT",
    "integer": "INT",
    "bigint": "BIGINT",
    "serial": "INT AUTO_INCREMENT",
    "bigserial": "BIGINT AUTO_INCREMENT",
    "numeric": "DECIMAL(p,s)",
    "real": "FLOAT",
    "double precision": "DOUBLE",
    "boolean": "BOOLEAN (TINYINT(1))",
    "character varying": "VARCHAR(n)",
    "character": "CHAR(n)",
    "text": "TEXT, or VARCHAR(n) when the max length is known",
    "date": "DATE",
    "timestamp without time zone": "DATETIME",
    "timestamp with time zone": "DATETIME (normalized to UTC)",
    "time without time zone": "TIME",
    "uuid": "CHAR(36)",
    "json": "JSON",
    "jsonb": "JSON",
    "bytea": "LONGBLOB",
    "ARRAY": "JSON",
}

# Semantic type -> (canonical type, constraint rule or None)
SEMANTIC_RULES = {
    "money": ("DECIMAL(12,2)", ("ge", 0)),
    "percentage": ("DECIMAL(5,4)", ("between", 0, 1)),
    "age": ("SMALLINT", ("between", 16, 100)),
    "quantity": ("INT", ("gt", 0)),
    "rating": ("DECIMAL(3,1)", ("between", 0, 5)),
    "email": ("VARCHAR(255)", ("email",)),
    "phone": ("CHAR(10)", ("digits", 10)),
    "bool": ("BOOLEAN", None),
    "date": ("DATE", None),
    "datetime": ("DATETIME", None),
    "int": ("INT", None),
    "float": ("DOUBLE", None),
}

MYSQL = DIALECTS["mysql"]


def q(name: str) -> str:
    """Quote a validated identifier for MySQL (kept for backwards compatibility)."""
    return MYSQL.q(name)


@dataclass
class ColumnDef:
    name: str
    sql_type: str            # canonical type, e.g. DECIMAL(12,2)
    nullable: bool
    semantic: str
    rule: tuple | None = None
    references: tuple | None = None   # (table, column)

    def check(self, dialect=MYSQL):
        return dialect.check_sql(self.rule, self.name)


@dataclass
class TableDef:
    name: str
    columns: list
    primary_key: str | None
    indexes: list = field(default_factory=list)     # column names
    uniques: list = field(default_factory=list)     # column names
    dependents: list = field(default_factory=list)  # columns moved out by normalization (FD on the lookup key)

    def create_sql(self, physical_name=None, ref_map=None, include_indexes=True, dialect=MYSQL) -> str:
        """Render CREATE TABLE. ref_map renames referenced tables (e.g. to staging names)."""
        tname = physical_name or self.name
        ref_map = ref_map or {}
        lines = [f"  {dialect.q(c.name)} {dialect.map_type(c.sql_type)}{'' if c.nullable else ' NOT NULL'}"
                 for c in self.columns]
        if self.primary_key:
            lines.append(f"  PRIMARY KEY ({dialect.q(self.primary_key)})")
        for col in self.uniques:
            lines.append(f"  UNIQUE ({dialect.q(col)})")
        for c in self.columns:
            chk = c.check(dialect)
            if chk:
                lines.append(f"  CHECK ({chk})")
        for c in self.columns:
            if c.references:
                rt, rc = c.references
                lines.append(f"  FOREIGN KEY ({dialect.q(c.name)}) REFERENCES {dialect.q(ref_map.get(rt, rt))} ({dialect.q(rc)})")
        if include_indexes and dialect.name == "mysql":
            for col in self.indexes:
                lines.append(f"  INDEX {dialect.q(index_name(self.name, col))} ({dialect.q(col)})")
        suffix = " ENGINE=InnoDB DEFAULT CHARSET=utf8mb4" if dialect.name == "mysql" else ""
        return f"CREATE TABLE {dialect.q(tname)} (\n" + ",\n".join(lines) + "\n)" + suffix

    def index_sql(self, dialect, physical_name=None):
        t = physical_name or self.name
        return [dialect.create_index_sql(t, index_name(self.name, col), col) for col in self.indexes]


def index_name(table, col):
    """Index names are schema-wide in PostgreSQL/SQLite/DuckDB, so include the table."""
    return f"idx_{table}_{col}"[:60]


def _varchar_for(series: pd.Series) -> str:
    lengths = series.dropna().astype(str).str.len()
    longest = int(lengths.max()) if len(lengths) else 0
    if longest > 1000:
        return "TEXT"
    for size in (16, 32, 64, 128, 255, 1000):
        if longest * 1.5 <= size or size == 1000:
            return f"VARCHAR({size})"
    return "TEXT"


def column_sql_type(series: pd.Series, semantic: str) -> str:
    if semantic == "pk":
        if pd.api.types.is_integer_dtype(series):
            return "BIGINT" if series.max() > 2_000_000_000 else "INT"
        return _varchar_for(series)
    if semantic in SEMANTIC_RULES:
        return SEMANTIC_RULES[semantic][0]
    if pd.api.types.is_bool_dtype(series):
        return "BOOLEAN"
    if pd.api.types.is_integer_dtype(series):
        return "INT"
    if pd.api.types.is_float_dtype(series):
        return "DOUBLE"
    if pd.api.types.is_datetime64_any_dtype(series):
        return "DATETIME"
    return _varchar_for(series)


def design_table(df: pd.DataFrame, table: str, semantics: dict, primary_key: str | None,
                 index_columns=()) -> TableDef:
    safe_ident(table)
    cols = []
    for name in df.columns:
        safe_ident(name)
        sem = semantics.get(name, "text")
        rule = SEMANTIC_RULES.get(sem, (None, None))[1]
        cols.append(ColumnDef(
            name=name,
            sql_type=column_sql_type(df[name], sem),
            nullable=bool(df[name].isna().any()) and name != primary_key,
            semantic=sem,
            rule=rule,
        ))
    return TableDef(name=table, columns=cols, primary_key=primary_key, indexes=list(index_columns))


def functional_dependents(df: pd.DataFrame, column: str, semantics: dict) -> list:
    """
    Categorical columns C for which column -> C holds in the data (every value of
    `column` maps to at most one value of C). These move into the lookup table
    together with `column`, which removes the transitive dependency pk -> column -> C.
    """
    deps = []
    keyed = df.dropna(subset=[column])
    for c in df.columns:
        if c == column or semantics.get(c) != "category" or keyed[c].isna().all():
            continue
        if (keyed.groupby(column)[c].nunique() <= 1).all():
            deps.append(c)
    return deps


def normalize_lookup(df: pd.DataFrame, column: str, lookup_table: str, dependents=()):
    """
    Extract a repeating column (plus the columns functionally dependent on it)
    into its own table.

    Returns (lookup_df, main_df, fk_col): lookup_df has (id, <column>, <dependents...>)
    with one row per distinct value; main_df has those columns replaced by
    <column>_id referencing lookup.id.
    """
    safe_ident(lookup_table)
    dependents = list(dependents)
    keyed = df.dropna(subset=[column])
    values = sorted(keyed[column].unique())
    lookup_df = pd.DataFrame({"id": range(1, len(values) + 1), column: values})
    for dep in dependents:
        first = keyed.dropna(subset=[dep]).groupby(column)[dep].first()
        lookup_df[dep] = lookup_df[column].map(first)
    id_for = dict(zip(values, lookup_df["id"]))
    main_df = df.copy()
    pos = list(main_df.columns).index(column)
    fk_col = f"{column}_id"
    main_df.insert(pos, fk_col, main_df[column].map(id_for).astype("Int64"))
    main_df = main_df.drop(columns=[column, *dependents])
    return lookup_df, main_df, fk_col


def design_normalized(df, table, semantics, primary_key, column, lookup_table, index_columns=()):
    dependents = functional_dependents(df, column, semantics)
    lookup_df, main_df, fk_col = normalize_lookup(df, column, lookup_table, dependents)
    lookup_cols = [ColumnDef("id", "INT", False, "pk"),
                   ColumnDef(column, _varchar_for(lookup_df[column]), False, "category")]
    for dep in dependents:
        lookup_cols.append(ColumnDef(dep, _varchar_for(lookup_df[dep]), bool(lookup_df[dep].isna().any()), "category"))
    lookup_def = TableDef(name=lookup_table, columns=lookup_cols, primary_key="id", uniques=[column])
    sem = dict(semantics)
    sem[fk_col] = "int"
    main_def = design_table(main_df, table, sem, primary_key,
                            index_columns=[c for c in index_columns if c in main_df.columns])
    for c in main_def.columns:
        if c.name == fk_col:
            c.references = (lookup_table, "id")
    main_def.dependents = dependents
    return lookup_def, lookup_df, main_def, main_df


def to_db_value(v):
    """Convert pandas/numpy scalars to plain Python values for a DB driver."""
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(v, pd.Timestamp):
        return v.to_pydatetime()
    if hasattr(v, "item"):
        v = v.item()
    if isinstance(v, float) and math.isnan(v):
        return None
    return v
