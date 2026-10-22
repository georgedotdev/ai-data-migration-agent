"""Convert pipeline results (DataFrames, numpy, Decimal, datetimes, NaN) into JSON-safe values."""

import math
from datetime import date, datetime, time
from decimal import Decimal

import numpy as np
import pandas as pd


def table(df: pd.DataFrame | None, limit: int | None = None) -> dict:
    """DataFrame -> {"columns": [...], "rows": [[...], ...]}."""
    if df is None:
        return {"columns": [], "rows": []}
    if limit is not None:
        df = df.head(limit)
    return {"columns": [str(c) for c in df.columns],
            "rows": [[jsonable(v) for v in row] for row in df.itertuples(index=False, name=None)]}


def jsonable(v):
    if v is None:
        return None
    if isinstance(v, pd.DataFrame):
        return table(v)
    if isinstance(v, pd.Series):
        return [jsonable(x) for x in v.tolist()]
    if isinstance(v, dict):
        return {str(k): jsonable(x) for k, x in v.items()}
    if isinstance(v, (list, tuple, set)):
        return [jsonable(x) for x in v]
    if isinstance(v, (str, bool)):
        return v
    if isinstance(v, np.bool_):
        return bool(v)
    if isinstance(v, (int, np.integer)):
        return int(v)
    if isinstance(v, (float, np.floating)):
        f = float(v)
        return None if math.isnan(f) or math.isinf(f) else f
    if isinstance(v, Decimal):
        return float(v) if v == v else None
    if isinstance(v, pd.Timestamp):
        return None if pd.isna(v) else v.isoformat()
    if isinstance(v, (datetime, date, time)):
        return v.isoformat()
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    return str(v)
