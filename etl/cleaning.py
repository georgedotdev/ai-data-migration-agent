"""
Deterministic migration cleaner (no LLM required).

Turns a raw legacy table (usually all-text columns) into typed, validated data
that can be loaded under strict database constraints. Rows that cannot be
migrated (no primary key, conflicting duplicate key) are not dropped silently:
they are moved to a quarantine set with a reason, so the row accounting
    source_rows = loaded_rows + exact_duplicates_removed + quarantined_rows
always balances.

Missing values are left as NULL rather than imputed, so the target never
contains values that were not in the source.
"""

import difflib
import re
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

SENTINELS = {"", "UNKNOWN", "N/A", "NA", "NONE", "NULL", "NAN", "-", "?", "TBD", "ERROR",
             "MISSING", "NOT RECORDED", "UNDEFINED"}
TRUE_WORDS = {"true", "t", "yes", "y", "1"}
FALSE_WORDS = {"false", "f", "no", "n", "0"}
EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$")
CURRENCY_RE = re.compile(r"(?i)^\s*(?:usd|inr|rs\.?|eur|gbp|[$€£₹])?\s*(-?[\d,]*\.?\d+)\s*(k)?\s*(?:usd|inr|eur|gbp)?\s*$")
RATIO_RE = re.compile(r"^\s*(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)\s*$")
PERCENT_RE = re.compile(r"^\s*(-?\d+(?:\.\d+)?)\s*%\s*$")
DATE_HINT_RE = re.compile(r"\d{1,4}[-/.]\d{1,2}[-/.]\d{1,4}|[A-Za-z]{3,9}\s+\d{1,2},?\s+\d{4}")

# Column-name keywords that drive domain validation (semantic type -> keywords)
NAME_HINTS = {
    "money": ("salary", "price", "amount", "total", "cost", "revenue", "bonus", "fee"),
    "percentage": ("discount", "percent", "pct", "rate_pct"),
    "age": ("age",),
    "quantity": ("quantity", "qty", "units"),
    "rating": ("rating", "score", "stars"),
    "email": ("email",),
    "phone": ("phone", "mobile", "contact_no"),
}

# Checks applied per semantic type: (description, predicate on a numeric/str value)
DOMAIN_RULES = {
    "money": ("must be >= 0", lambda v: v >= 0),
    "percentage": ("must be between 0 and 1", lambda v: 0 <= v <= 1),
    "age": ("must be between 16 and 100", lambda v: 16 <= v <= 100),
    "quantity": ("must be > 0", lambda v: v > 0),
    "rating": ("must be between 0 and 5", lambda v: 0 <= v <= 5),
}


@dataclass
class CleanResult:
    df: pd.DataFrame
    log: list
    quarantine: pd.DataFrame
    semantics: dict            # column -> semantic type (pk, money, date, category, ...)
    primary_key: str | None
    stats: dict = field(default_factory=dict)
    column_map: dict = field(default_factory=dict)   # raw source name -> cleaned name


def snake_case(name):
    s = re.sub(r"[^a-zA-Z0-9]+", "_", str(name).strip()).strip("_").lower()
    return s or "col"


def _hint(col):
    for sem, words in NAME_HINTS.items():
        if any(w in col for w in words):
            return sem
    return None


def _parse_number(val):
    """Parse '$1,200', '55k', 'USD 72,500', '4.5/5' -> float, else None."""
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return None
    if isinstance(val, (int, float, np.number)):
        return float(val)
    s = str(val).strip()
    m = RATIO_RE.match(s)
    if m:
        num, den = float(m.group(1)), float(m.group(2))
        return num if den == 5 else (num / den * 5 if den else None)
    m = CURRENCY_RE.match(s)
    if not m:
        return None
    try:
        num = float(m.group(1).replace(",", ""))
    except ValueError:
        return None
    return num * 1000 if m.group(2) else num


def _parse_percentage(val):
    """'15%', '15 %' -> 0.15; '0.15' -> 0.15; '15' -> 0.15."""
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return None
    s = str(val).strip()
    m = PERCENT_RE.match(s)
    if m:
        return float(m.group(1)) / 100.0
    num = _parse_number(s)
    if num is None:
        return None
    return num / 100.0 if num > 1 else num


def _normalize_key(s):
    return re.sub(r"[^a-z0-9]", "", str(s).lower())


def _initials(s):
    return "".join(w[0] for w in re.findall(r"[A-Za-z]+", str(s))).lower()


def clean_for_migration(raw: pd.DataFrame) -> CleanResult:
    df = raw.copy()
    df.index = pd.RangeIndex(len(df))
    raw_indexed = df.copy()
    log = []

    def note(column, action, detail, rows=0):
        log.append({"column": str(column), "action": action, "detail": detail, "rows_affected": int(rows)})

    # 1. Header standardization
    new_cols, seen = [], {}
    for c in df.columns:
        n = snake_case(c)
        if n in seen:
            seen[n] += 1
            n = f"{n}_{seen[n]}"
        else:
            seen[n] = 0
        if n != c:
            note(c, "standardize_column_name", f"'{c}' -> '{n}'")
        new_cols.append(n)
    column_map = dict(zip(raw.columns, new_cols))
    df.columns = new_cols
    raw_indexed.columns = new_cols

    # 2. Whitespace and sentinel values
    for col in df.columns:
        if df[col].dtype != object:
            continue
        before = df[col]
        stripped = before.map(lambda v: re.sub(r"\s+", " ", v).strip() if isinstance(v, str) else v)
        changed = int((before.notna() & (before != stripped)).sum())
        if changed:
            note(col, "trim_whitespace", f"Trimmed/collapsed whitespace in {changed} values", changed)
        is_sentinel = stripped.map(lambda v: isinstance(v, str) and v.upper() in SENTINELS)
        n_sent = int(is_sentinel.sum())
        if n_sent:
            stripped = stripped.mask(is_sentinel, None)
            note(col, "sentinel_to_null", f"Replaced {n_sent} placeholder values (blank, N/A, UNKNOWN, -, ?) with NULL", n_sent)
        df[col] = stripped

    # 3. Primary key detection: an id-like column that is mostly unique
    pk = None
    for col in df.columns:
        if col == "id" or col.endswith("_id"):
            nn = df[col].dropna()
            if len(nn) and nn.nunique() / len(nn) >= 0.9:
                pk = col
                break
    semantics = {}
    if pk:
        semantics[pk] = "pk"
        note(pk, "detect_primary_key", f"'{pk}' chosen as primary key ({df[pk].nunique()} distinct values)")

    # 4. Per-column type inference and domain validation
    for col in df.columns:
        s = df[col]
        nn = s.dropna()
        if col == pk:
            nums = nn.map(_parse_number)
            if len(nn) and nums.notna().all() and (nums % 1 == 0).all():
                df[col] = s.map(lambda v: int(_parse_number(v)) if v is not None else None).astype("Int64")
            continue
        if len(nn) == 0:
            semantics[col] = "text"
            continue
        hint = _hint(col)
        lower = nn.astype(str).str.lower()

        # Boolean
        if lower.isin(TRUE_WORDS | FALSE_WORDS).all() and lower.nunique() > 1:
            df[col] = s.map(lambda v: None if v is None else str(v).lower() in TRUE_WORDS).astype("boolean")
            variants = sorted(nn.astype(str).unique())
            note(col, "normalize_boolean", f"Mapped {len(variants)} spellings ({', '.join(variants[:8])}) to TRUE/FALSE", len(nn))
            semantics[col] = "bool"
            continue

        # Email
        if hint == "email":
            valid = nn.astype(str).str.match(EMAIL_RE)
            bad = int((~valid).sum())
            df[col] = s.map(lambda v: v.lower() if isinstance(v, str) and EMAIL_RE.match(v) else None)
            if bad:
                note(col, "validate_email", f"{bad} malformed emails set to NULL (e.g. {nn[~valid].iloc[0]!r})", bad)
            semantics[col] = "email"
            continue

        # Phone
        if hint == "phone":
            def _phone(v):
                if v is None:
                    return None
                d = re.sub(r"\D", "", str(v))
                if len(d) == 12 and d.startswith("91"):
                    d = d[2:]
                return d if len(d) == 10 else None
            out = s.map(_phone)
            changed = int((out.notna() & (out != s)).sum())
            invalid = int((s.notna() & out.isna()).sum())
            df[col] = out
            note(col, "normalize_phone", f"Normalized {changed} phone numbers to 10 digits; {invalid} invalid set to NULL", changed + invalid)
            semantics[col] = "phone"
            continue

        # Percentage
        if hint == "percentage" or nn.astype(str).str.contains("%").mean() > 0.5:
            parsed = s.map(_parse_percentage)
            if parsed[s.notna()].notna().mean() >= 0.8:
                df[col] = parsed.astype("float64")
                note(col, "parse_percentage", f"Parsed {int(parsed.notna().sum())} values ('15%', '15 %', '0.15') to fractions 0-1", int(parsed.notna().sum()))
                semantics[col] = "percentage"
                _apply_domain(df, col, "percentage", note)
                continue

        # Numeric (currency, k-suffix, ratios)
        parsed = s.map(_parse_number)
        ok_ratio = parsed[s.notna()].notna().mean()
        needed = 0.6 if hint in ("money", "age", "quantity", "rating") else 0.8
        if ok_ratio >= needed and not lower.str.match(r"^\d{1,4}[-/.]\d{1,2}[-/.]\d").mean() > 0.5:
            unparseable = int((s.notna() & parsed.isna()).sum())
            reformatted = int((s.notna() & parsed.notna() & s.astype(str).str.contains(r"[^\d.\-]")).sum())
            is_int = parsed.dropna().mod(1).eq(0).all() and hint not in ("money", "rating")
            df[col] = parsed.round().astype("Int64") if is_int else parsed.astype("float64")
            sem = hint if hint in ("money", "age", "quantity", "rating") else ("int" if is_int else "float")
            semantics[col] = sem
            note(col, "parse_numeric", f"Parsed {int(parsed.notna().sum())} numeric values"
                 + (f" ({reformatted} had non-standard formatting: currency symbols, commas, k-suffix or x/5)" if reformatted else "")
                 + (f"; {unparseable} unparseable values (e.g. {s[s.notna() & parsed.isna()].iloc[0]!r}) set to NULL" if unparseable else ""),
                 reformatted + unparseable)
            _apply_domain(df, col, sem, note)
            continue

        # Date
        if nn.astype(str).str.contains(DATE_HINT_RE).mean() >= 0.6:
            parsed = pd.to_datetime(s, errors="coerce", format="mixed")
            invalid = int((s.notna() & parsed.isna()).sum())
            future = parsed > pd.Timestamp.now()
            n_future = int(future.sum())
            parsed = parsed.mask(future)
            df[col] = parsed
            has_time = (parsed.dropna().dt.normalize() != parsed.dropna()).any()
            semantics[col] = "datetime" if has_time else "date"
            note(col, "parse_date", f"Unified {int(parsed.notna().sum())} dates from mixed formats to ISO"
                 + (f"; {invalid} unparseable (e.g. {s[s.notna() & pd.to_datetime(s, errors='coerce', format='mixed').isna()].iloc[0]!r}) set to NULL" if invalid else "")
                 + (f"; {n_future} future dates set to NULL" if n_future else ""), int(parsed.notna().sum()) + invalid)
            continue

        # Categorical vs free text
        n_unique = nn.map(_normalize_key).nunique()
        if n_unique <= 25 and n_unique <= max(5, 0.2 * len(nn)) and not col.endswith("name"):
            _canonicalize_category(df, col, note)
            semantics[col] = "category"
        else:
            semantics[col] = "text"

    # 5. Exact duplicate rows
    before = len(df)
    dup_mask = df.duplicated(keep="first")
    df = df[~dup_mask]
    exact_dupes = before - len(df)
    if exact_dupes:
        note("ALL_COLUMNS", "remove_exact_duplicates", f"Removed {exact_dupes} rows that were exact copies of another row", exact_dupes)

    # 6. Quarantine rows that violate key integrity
    q_parts = []
    if pk:
        missing = df[pk].isna()
        if missing.any():
            q_parts.append(_quarantine(raw_indexed, df.index[missing], f"missing primary key '{pk}'"))
            note(pk, "quarantine_missing_pk", f"{int(missing.sum())} rows have no {pk}; moved to quarantine", int(missing.sum()))
            df = df[~missing]
        dup_key = df.duplicated(subset=[pk], keep="first")
        if dup_key.any():
            q_parts.append(_quarantine(raw_indexed, df.index[dup_key], f"duplicate primary key '{pk}' with conflicting values"))
            note(pk, "quarantine_duplicate_pk", f"{int(dup_key.sum())} rows reuse an existing {pk} with different values; first kept, rest quarantined", int(dup_key.sum()))
            df = df[~dup_key]

    quarantine = pd.concat(q_parts) if q_parts else pd.DataFrame(columns=["source_row", "reason", "raw"])
    df = df.reset_index(drop=True)

    stats = {
        "source_rows": len(raw),
        "loaded_rows": len(df),
        "exact_duplicates_removed": exact_dupes,
        "quarantined_rows": len(quarantine),
        "null_cells_before": int(raw.replace("", np.nan).isna().sum().sum()),
        "null_cells_after": int(df.isna().sum().sum()),
    }
    return CleanResult(df=df, log=log, quarantine=quarantine, semantics=semantics, primary_key=pk, stats=stats,
                       column_map=column_map)


def _apply_domain(df, col, sem, note):
    rule = DOMAIN_RULES.get(sem)
    if not rule:
        return
    desc, ok = rule
    bad = df[col].notna() & ~df[col].map(lambda v: bool(ok(v)) if pd.notna(v) else True)
    n_bad = int(bad.sum())
    if n_bad:
        examples = df.loc[bad, col].head(3).tolist()
        df.loc[bad, col] = pd.NA if str(df[col].dtype) == "Int64" else np.nan
        note(col, "domain_check", f"{n_bad} values violated rule '{col} {desc}' (e.g. {examples}); set to NULL", n_bad)


def _canonicalize_category(df, col, note):
    s = df[col]
    counts = s.dropna().value_counts()
    # Group spellings that differ only by case/spacing/punctuation
    groups = {}
    for val, cnt in counts.items():
        groups.setdefault(_normalize_key(val), []).append((val, cnt))
    canon_for_key = {}
    key_totals = {}
    for key, members in groups.items():
        best = max(members, key=lambda m: (m[1], m[0].istitle(), m[0]))[0]
        if best.isupper() or best.islower():
            best = best.title() if len(best) > 3 else best.upper()
        canon_for_key[key] = best
        key_totals[key] = sum(c for _, c in members)
    # Fold rare typo/abbreviation variants into a much more frequent group
    keys_by_freq = sorted(key_totals, key=key_totals.get, reverse=True)
    for key in keys_by_freq[::-1]:
        for target in keys_by_freq:
            if target == key or key_totals[target] < 3 * key_totals[key]:
                continue
            similar = difflib.SequenceMatcher(None, key, target).ratio() >= 0.85
            acronym = len(key) >= 2 and key == _initials(canon_for_key[target])
            if similar or acronym:
                canon_for_key[key] = canon_for_key[target]
                break
    mapping = {val: canon_for_key[_normalize_key(val)] for val in counts.index}
    changed = {k: v for k, v in mapping.items() if k != v}
    if changed:
        df[col] = s.map(lambda v: mapping.get(v, v) if v is not None else None)
        rows = int(s.isin(list(changed)).sum())
        sample = ", ".join(f"'{k}'->'{v}'" for k, v in list(changed.items())[:5])
        note(col, "canonicalize_category", f"Merged {len(changed)} spelling variants into {df[col].nunique()} categories ({sample})", rows)


def _quarantine(raw_indexed, idx, reason):
    rows = raw_indexed.loc[idx]
    return pd.DataFrame({
        "source_row": [int(i) + 1 for i in idx],
        "reason": reason,
        "raw": [r.to_json() for _, r in rows.iterrows()],
    })
