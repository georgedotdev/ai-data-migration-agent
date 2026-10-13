"""
Target schema design for MySQL.

Instead of letting pandas.to_sql guess column types, the migration derives an
explicit MySQL schema from the cleaned data and its semantic types:
data types, PRIMARY KEY, NOT NULL, CHECK and FOREIGN KEY constraints.
"""

import math
import re
from dataclasses import dataclass, field

import pandas as pd

IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,47}$")

# Reference mapping used when the PostgreSQL source column is already typed.
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

# Semantic type -> (MySQL type, CHECK expression template or None)
SEMANTIC_RULES = {
    "money": ("DECIMAL(12,2)", "{c} >= 0"),
    "percentage": ("DECIMAL(5,4)", "{c} BETWEEN 0 AND 1"),
    "age": ("SMALLINT", "{c} BETWEEN 16 AND 100"),
    "quantity": ("INT", "{c} > 0"),
    "rating": ("DECIMAL(3,1)", "{c} BETWEEN 0 AND 5"),
    "email": ("VARCHAR(255)", "{c} LIKE '%_@_%._%'"),
    "phone": ("CHAR(10)", "{c} REGEXP '^[0-9]{{10}}$'"),
    "bool": ("BOOLEAN", None),
    "date": ("DATE", None),
    "datetime": ("DATETIME", None),
    "int": ("INT", None),
    "float": ("DOUBLE", None),
}


def safe_ident(name: str) -> str:
    """Validate a table/column identifier so it can be safely quoted into SQL."""
    if not isinstance(name, str) or not IDENT_RE.match(name):
        raise ValueError(
            f"Invalid identifier {name!r}: use letters, digits and underscores, "
            "start with a letter or underscore, max 48 characters."
        )
    return name


def q(name: str) -> str:
    """Quote a validated identifier for MySQL."""
    return f"`{safe_ident(name)}`"


@dataclass
class ColumnDef:
    name: str
    sql_type: str
    nullable: bool
    semantic: str
    check: str | None = None
    references: tuple | None = None   # (table, column)


@dataclass
class TableDef:
    name: str
    columns: list
    primary_key: str | None
    indexes: list = field(default_factory=list)   # column names
    uniques: list = field(default_factory=list)   # column names

    def create_sql(self, physical_name: str | None = None, ref_map: dict | None = None,
                   include_indexes: bool = True) -> str:
        """Render CREATE TABLE. ref_map renames referenced tables (e.g. to staging names)."""
        tname = physical_name or self.name
        ref_map = ref_map or {}
        lines = []
        for c in self.columns:
            line = f"  {q(c.name)} {c.sql_type}{'' if c.nullable else ' NOT NULL'}"
            lines.append(line)
        if self.primary_key:
            lines.append(f"  PRIMARY KEY ({q(self.primary_key)})")
        for col in self.uniques:
            lines.append(f"  UNIQUE KEY {q('uq_' + col)} ({q(col)})")
        for c in self.columns:
            if c.check:
                lines.append(f"  CHECK ({c.check})")
        for c in self.columns:
            if c.references:
                rt, rc = c.references
                lines.append(f"  FOREIGN KEY ({q(c.name)}) REFERENCES {q(ref_map.get(rt, rt))} ({q(rc)})")
        for col in (self.indexes if include_indexes else []):
            lines.append(f"  INDEX {q('idx_' + col)} ({q(col)})")
        return f"CREATE TABLE {q(tname)} (\n" + ",\n".join(lines) + "\n) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4"


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
        rule = SEMANTIC_RULES.get(sem)
        check = rule[1].format(c=q(name)) if rule and rule[1] else None
        cols.append(ColumnDef(
            name=name,
            sql_type=column_sql_type(df[name], sem),
            nullable=bool(df[name].isna().any()) and name != primary_key,
            semantic=sem,
            check=check,
        ))
    return TableDef(name=table, columns=cols, primary_key=primary_key, indexes=list(index_columns))


def normalize_lookup(df: pd.DataFrame, column: str, lookup_table: str):
    """
    Extract a repeating categorical column into its own table (3NF).

    Returns (lookup_df, main_df): lookup_df has (id, <column>) with one row per
    distinct value; main_df has <column> replaced by <column>_id referencing it.
    """
    safe_ident(lookup_table)
    values = sorted(df[column].dropna().unique())
    lookup_df = pd.DataFrame({"id": range(1, len(values) + 1), column: values})
    id_for = dict(zip(values, lookup_df["id"]))
    main_df = df.copy()
    pos = list(main_df.columns).index(column)
    fk_col = f"{column}_id"
    main_df.insert(pos, fk_col, main_df[column].map(id_for).astype("Int64"))
    main_df = main_df.drop(columns=[column])
    return lookup_df, main_df, fk_col


def design_normalized(df, table, semantics, primary_key, column, lookup_table, index_columns=()):
    lookup_df, main_df, fk_col = normalize_lookup(df, column, lookup_table)
    lookup_def = TableDef(
        name=lookup_table,
        columns=[
            ColumnDef("id", "INT", False, "pk"),
            ColumnDef(column, _varchar_for(lookup_df[column]), False, "category"),
        ],
        primary_key="id",
        uniques=[column],
    )
    sem = dict(semantics)
    sem[fk_col] = "int"
    main_def = design_table(main_df, table, sem, primary_key,
                            index_columns=[c for c in index_columns if c in main_df.columns])
    for c in main_def.columns:
        if c.name == fk_col:
            c.references = (lookup_table, "id")
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
