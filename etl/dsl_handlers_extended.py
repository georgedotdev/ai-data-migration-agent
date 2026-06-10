import re
import pandas as pd
import numpy as np
import json
import uuid

# ─────────────────────────────────────────────
# Category 1: Missing Data (Extended)
# ─────────────────────────────────────────────
def _action_drop_missing_rows(df: pd.DataFrame, step: dict):
    column = step.get("column")
    df = df.copy()
    rows_before = len(df)
    if column:
        if column not in df.columns:
            return df, {"status": "error", "details": {"error": f"Column '{column}' not found"}}
        df = df.dropna(subset=[column])
    else:
        df = df.dropna()
    return df, {"status": "success", "details": {"rows_removed": rows_before - len(df)}}

# ─────────────────────────────────────────────
# Category 2: Duplicates (Extended)
# ─────────────────────────────────────────────
def _action_keep_latest_duplicate(df: pd.DataFrame, step: dict):
    column = step.get("column")
    timestamp_col = step.get("timestamp_column")
    
    # Phase 3: Auto-infer timestamp column if missing
    if not timestamp_col:
        datetime_cols = [c for c in df.columns if pd.api.types.is_datetime64_any_dtype(df[c])]
        if len(datetime_cols) == 1:
            timestamp_col = datetime_cols[0]
        elif len(datetime_cols) > 1:
            candidates = [c for c in datetime_cols if any(kw in c.lower() for kw in ("date", "time", "created", "updated"))]
            timestamp_col = candidates[0] if candidates else datetime_cols[0]

    if not column or not timestamp_col:
        return df, {"status": "error", "details": {"error": "Requires 'column' and 'timestamp_column' (auto-inference failed: no datetime columns found)"}}
    if column not in df.columns or timestamp_col not in df.columns:
        return df, {"status": "error", "details": {"error": "Column not found"}}
    
    df = df.copy()
    rows_before = len(df)
    
    # Sort by timestamp, then drop duplicates keeping the last
    # We assume timestamp_col is sortable
    df = df.sort_values(by=timestamp_col)
    df = df.drop_duplicates(subset=[column], keep="last").reset_index(drop=True)
    
    return df, {"status": "success", "details": {"rows_removed": rows_before - len(df), "inferred_timestamp_column": timestamp_col}}


# ─────────────────────────────────────────────
# Category 4: Date & Time Parsing
# ─────────────────────────────────────────────
def _action_parse_datetime(df: pd.DataFrame, step: dict):
    column = step.get("column")
    if not column or column not in df.columns:
        return df, {"status": "error", "details": {"error": "Invalid column"}}
    
    df = df.copy()
    df[column] = pd.to_datetime(df[column], errors="coerce", format="mixed")
    return df, {"status": "success", "details": {"column": column}}

def _action_extract_datetime_part(df: pd.DataFrame, step: dict, part: str):
    column = step.get("column")
    if not column or column not in df.columns:
        return df, {"status": "error", "details": {"error": "Invalid column"}}
    
    df = df.copy()
    new_col = f"{column}_{part}"
    
    temp_dt = pd.to_datetime(df[column], errors="coerce")
    if part == "year":
        df[new_col] = temp_dt.dt.year
    elif part == "month":
        df[new_col] = temp_dt.dt.month
    elif part == "day":
        df[new_col] = temp_dt.dt.day
        
    return df, {"status": "success", "details": {"new_column": new_col}}

def _action_extract_year(df, step): return _action_extract_datetime_part(df, step, "year")
def _action_extract_month(df, step): return _action_extract_datetime_part(df, step, "month")
def _action_extract_day(df, step): return _action_extract_datetime_part(df, step, "day")

# ─────────────────────────────────────────────
# Category 5: Currency Parsing
# ─────────────────────────────────────────────
def _action_parse_currency(df: pd.DataFrame, step: dict):
    column = step.get("column")
    if not column or column not in df.columns:
        return df, {"status": "error", "details": {"error": "Invalid column"}}
    
    df = df.copy()
    def parse_curr(val):
        if pd.isna(val): return val
        val_str = str(val).upper().replace(",", "").strip()
        val_str = re.sub(r'[^0-9\.MK]', '', val_str) # Keep digits, dot, M, K
        if not val_str: return np.nan
        
        multiplier = 1
        if val_str.endswith("M"):
            multiplier = 1_000_000
            val_str = val_str[:-1]
        elif val_str.endswith("K"):
            multiplier = 1_000
            val_str = val_str[:-1]
            
        try:
            return float(val_str) * multiplier
        except:
            return np.nan

    df_before = df.copy()
    df[column] = df[column].apply(parse_curr)
    
    # Phase 2: Capture Data Quarantine events
    was_not_null = ~df_before[column].isna()
    is_now_null = df[column].isna()
    coerced_to_nan = was_not_null & is_now_null

    return df, {
        "status": "success", 
        "details": {
            "column": column,
            "coerced_to_nan_count": int(coerced_to_nan.sum()),
            "coerced_indices": df.index[coerced_to_nan].tolist()[:20]
        }
    }

# ─────────────────────────────────────────────
# Category 6: Measurement Parsing
# ─────────────────────────────────────────────
def _action_parse_height(df: pd.DataFrame, step: dict):
    column = step.get("column")
    if not column or column not in df.columns:
        return df, {"status": "error", "details": {"error": "Invalid column"}}
    
    df = df.copy()
    def to_cm(val):
        if pd.isna(val): return val
        val_str = str(val).lower()
        # look for X'Y" or X ft Y in
        match = re.search(r"(\d+)\s*(?:'|ft)\s*(\d+)?\s*(?:\"|in)?", val_str)
        if match:
            ft = int(match.group(1))
            inches = int(match.group(2)) if match.group(2) else 0
            return (ft * 30.48) + (inches * 2.54)
        return np.nan

    df[column] = df[column].apply(to_cm)
    return df, {"status": "success", "details": {"column": column}}

def _action_parse_weight(df: pd.DataFrame, step: dict):
    column = step.get("column")
    if not column or column not in df.columns:
        return df, {"status": "error", "details": {"error": "Invalid column"}}
    
    df = df.copy()
    def to_kg(val):
        if pd.isna(val): return val
        val_str = str(val).lower().strip()
        match = re.search(r"([\d\.]+)\s*(lbs?|kg)", val_str)
        if match:
            amt = float(match.group(1))
            unit = match.group(2)
            if "lb" in unit:
                return amt * 0.453592
            return amt
        return np.nan

    df[column] = df[column].apply(to_kg)
    return df, {"status": "success", "details": {"column": column}}

# ─────────────────────────────────────────────
# Category 7: Percentage Parsing
# ─────────────────────────────────────────────
def _action_parse_percentage(df: pd.DataFrame, step: dict):
    column = step.get("column")
    if not column or column not in df.columns:
        return df, {"status": "error", "details": {"error": "Invalid column"}}
    
    df = df.copy()
    def to_pct(val):
        if pd.isna(val): return val
        val_str = str(val).replace("%", "").strip()
        try:
            return float(val_str) / 100.0
        except:
            return np.nan

    df_before = df.copy()
    df[column] = df[column].apply(to_pct)
    
    # Phase 2: Capture Data Quarantine events
    was_not_null = ~df_before[column].isna()
    is_now_null = df[column].isna()
    coerced_to_nan = was_not_null & is_now_null

    return df, {
        "status": "success", 
        "details": {
            "column": column,
            "coerced_to_nan_count": int(coerced_to_nan.sum()),
            "coerced_indices": df.index[coerced_to_nan].tolist()[:20]
        }
    }

# ─────────────────────────────────────────────
# Category 8: Rating Parsing
# ─────────────────────────────────────────────
def _action_parse_rating(df: pd.DataFrame, step: dict):
    column = step.get("column")
    if not column or column not in df.columns:
        return df, {"status": "error", "details": {"error": "Invalid column"}}
    
    df = df.copy()
    def to_rating(val):
        if pd.isna(val): return val
        val_str = str(val)
        match = re.search(r"(\d+(?:\.\d+)?)", val_str)
        if match:
            return float(match.group(1))
        return np.nan

    df_before = df.copy()
    df[column] = df[column].apply(to_rating)
    
    # Phase 2: Capture Data Quarantine events
    was_not_null = ~df_before[column].isna()
    is_now_null = df[column].isna()
    coerced_to_nan = was_not_null & is_now_null

    return df, {
        "status": "success", 
        "details": {
            "column": column,
            "coerced_to_nan_count": int(coerced_to_nan.sum()),
            "coerced_indices": df.index[coerced_to_nan].tolist()[:20]
        }
    }

# ─────────────────────────────────────────────
# Category 9: String Cleaning
# ─────────────────────────────────────────────
def _action_string_clean(df: pd.DataFrame, step: dict, func):
    column = step.get("column")
    if not column or column not in df.columns:
        return df, {"status": "error", "details": {"error": "Invalid column"}}
    
    df = df.copy()
    df[column] = df[column].apply(lambda x: func(str(x)) if not pd.isna(x) else x)
    return df, {"status": "success", "details": {"column": column}}

def _action_strip_special_characters(df, step):
    return _action_string_clean(df, step, lambda x: re.sub(r'[^a-zA-Z0-9\s]', '', x))

def _action_trim_whitespace(df, step):
    return _action_string_clean(df, step, lambda x: x.strip())

def _action_normalize_case(df, step):
    return _action_string_clean(df, step, lambda x: x.lower())

def _action_remove_line_breaks(df, step):
    return _action_string_clean(df, step, lambda x: re.sub(r'[\r\n]+', ' ', x))

def _action_remove_non_ascii(df, step):
    return _action_string_clean(df, step, lambda x: x.encode('ascii', 'ignore').decode('ascii'))

# ─────────────────────────────────────────────
# Category 10: Column Splitting
# ─────────────────────────────────────────────
def _action_split_column(df: pd.DataFrame, step: dict):
    column = step.get("column")
    delimiter = step.get("delimiter")
    regex = step.get("regex")
    
    if not column or column not in df.columns:
        return df, {"status": "error", "details": {"error": "Invalid column"}}
    if not delimiter and not regex:
        return df, {"status": "error", "details": {"error": "Requires delimiter or regex"}}
        
    df = df.copy()
    if regex:
        splits = df[column].astype(str).str.split(regex, expand=True)
    else:
        splits = df[column].astype(str).str.split(delimiter, expand=True)
        
    for i in range(splits.shape[1]):
        df[f"{column}_{i+1}"] = splits[i]
        
    return df, {"status": "success", "details": {"column": column, "parts": splits.shape[1]}}

# ─────────────────────────────────────────────
# Category 11: Regex Extraction
# ─────────────────────────────────────────────
def _action_extract_pattern(df: pd.DataFrame, step: dict):
    column = step.get("column")
    regex = step.get("regex")
    if not column or column not in df.columns:
        return df, {"status": "error", "details": {"error": "Invalid column"}}
    if not regex:
        return df, {"status": "error", "details": {"error": "Requires regex"}}
        
    df = df.copy()
    df[f"{column}_extracted"] = df[column].astype(str).str.extract(f"({regex})")[0]
    return df, {"status": "success", "details": {"column": column}}

# ─────────────────────────────────────────────
# Category 12: Nested Object Handling
# ─────────────────────────────────────────────
def _action_explode_array(df: pd.DataFrame, step: dict):
    column = step.get("column")
    if not column or column not in df.columns:
        return df, {"status": "error", "details": {"error": "Invalid column"}}
        
    df = df.copy()
    # Assume column contains lists
    df = df.explode(column).reset_index(drop=True)
    return df, {"status": "success", "details": {"column": column}}

def _action_serialize_json(df: pd.DataFrame, step: dict):
    column = step.get("column")
    if not column or column not in df.columns:
        return df, {"status": "error", "details": {"error": "Invalid column"}}
        
    df = df.copy()
    df[column] = df[column].apply(lambda x: json.dumps(x) if isinstance(x, (dict, list)) else x)
    return df, {"status": "success", "details": {"column": column}}

# ─────────────────────────────────────────────
# Category 13: Schema Mapping Tools
# ─────────────────────────────────────────────
def _action_merge_columns(df: pd.DataFrame, step: dict):
    columns = step.get("columns", [])
    new_name = step.get("new_name")
    separator = step.get("separator", " ")
    
    if not columns or not new_name:
        return df, {"status": "error", "details": {"error": "Requires 'columns' (list) and 'new_name'"}}
        
    df = df.copy()
    df[new_name] = df[columns].astype(str).agg(separator.join, axis=1)
    return df, {"status": "success", "details": {"new_column": new_name}}

def _action_create_column(df: pd.DataFrame, step: dict):
    new_name = step.get("new_name")
    value = step.get("value")
    
    if not new_name:
        return df, {"status": "error", "details": {"error": "Requires 'new_name'"}}
        
    df = df.copy()
    df[new_name] = value
    return df, {"status": "success", "details": {"new_column": new_name}}

# ─────────────────────────────────────────────
# Category 14: Data Quality Tools
# ─────────────────────────────────────────────
def _action_validate_format(df: pd.DataFrame, step: dict, regex_pattern: str, name: str):
    column = step.get("column")
    if not column or column not in df.columns:
        return df, {"status": "error", "details": {"error": "Invalid column"}}
        
    df = df.copy()
    mask = df[column].astype(str).str.match(regex_pattern, na=False)
    # Replaces invalid values with None to preserve the row!
    df.loc[~mask, column] = None
    return df, {"status": "success", "details": {"column": column, "invalid_cleared": int((~mask).sum())}}

def _action_validate_email(df, step):
    return _action_validate_format(df, step, r"^[\w\.-]+@[\w\.-]+\.\w+$", "email")

def _action_validate_phone(df, step):
    return _action_validate_format(df, step, r"^\+?[\d\s-]{7,15}$", "phone")

def _action_validate_postal_code(df, step):
    return _action_validate_format(df, step, r"^[A-Za-z0-9\s-]{3,10}$", "postal")

def _action_validate_country_code(df, step):
    return _action_validate_format(df, step, r"^[A-Z]{2,3}$", "country")

def _action_validate_uuid(df, step):
    return _action_validate_format(df, step, r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$", "uuid")

# ─────────────────────────────────────────────
# Category 15: Outliers
# ─────────────────────────────────────────────
def _action_detect_outliers(df: pd.DataFrame, step: dict):
    # Appends boolean mask
    column = step.get("column")
    if not column or column not in df.columns:
        return df, {"status": "error", "details": {"error": "Invalid column"}}
        
    df = df.copy()
    col_data = pd.to_numeric(df[column], errors="coerce")
    Q1 = col_data.quantile(0.25)
    Q3 = col_data.quantile(0.75)
    IQR = Q3 - Q1
    is_outlier = (col_data < (Q1 - 1.5 * IQR)) | (col_data > (Q3 + 1.5 * IQR))
    df[f"{column}_is_outlier"] = is_outlier
    return df, {"status": "success", "details": {"outliers_found": int(is_outlier.sum())}}

def _action_clip_outliers(df: pd.DataFrame, step: dict):
    column = step.get("column")
    if not column or column not in df.columns:
        return df, {"status": "error", "details": {"error": "Invalid column"}}
        
    df = df.copy()
    col_data = pd.to_numeric(df[column], errors="coerce")
    Q1 = col_data.quantile(0.25)
    Q3 = col_data.quantile(0.75)
    IQR = Q3 - Q1
    lower_bound = Q1 - 1.5 * IQR
    upper_bound = Q3 + 1.5 * IQR
    df[column] = col_data.clip(lower=lower_bound, upper=upper_bound)
    return df, {"status": "success", "details": {"column": column}}

def _action_remove_outliers(df: pd.DataFrame, step: dict):
    column = step.get("column")
    if not column or column not in df.columns:
        return df, {"status": "error", "details": {"error": "Invalid column"}}
        
    df = df.copy()
    col_data = pd.to_numeric(df[column], errors="coerce")
    Q1 = col_data.quantile(0.25)
    Q3 = col_data.quantile(0.75)
    IQR = Q3 - Q1
    lower_bound = Q1 - 1.5 * IQR
    upper_bound = Q3 + 1.5 * IQR
    mask = (col_data >= lower_bound) & (col_data <= upper_bound)
    # keeping NA values as they are not explicitly outliers
    mask = mask | col_data.isna()
    rows_before = len(df)
    df = df[mask].reset_index(drop=True)
    return df, {"status": "success", "details": {"rows_removed": rows_before - len(df)}}

# ─────────────────────────────────────────────
# Category 16: Business Rules
# ─────────────────────────────────────────────
def _action_conditional_transform(df: pd.DataFrame, step: dict):
    condition = step.get("condition")
    operation = step.get("operation")
    if not condition or not operation:
        return df, {"status": "error", "details": {"error": "Requires 'condition' and 'operation'"}}
        
    df = df.copy()
    try:
        # Evaluate condition safely (query uses numexpr)
        mask = df.eval(condition)
        
        # Parse operation "set_null(column)" or similar
        # For simplicity in V2, if operation == "set_null", we need the column from the step
        # or we just support a "column" parameter to apply the operation to.
        column = step.get("column")
        if operation == "set_null" and column and column in df.columns:
            df.loc[mask, column] = None
        else:
            return df, {"status": "error", "details": {"error": "Unsupported operation or missing column"}}
            
        return df, {"status": "success", "details": {"rows_affected": int(mask.sum())}}
    except Exception as e:
        return df, {"status": "error", "details": {"error": str(e)}}

# ─────────────────────────────────────────────
# Category 17: Metadata Tools
# ─────────────────────────────────────────────
def _action_generate_surrogate_key(df: pd.DataFrame, step: dict):
    column = step.get("column", "surrogate_key")
    df = df.copy()
    df[column] = [str(uuid.uuid4()) for _ in range(len(df))]
    return df, {"status": "success", "details": {"column": column}}

def _action_metadata_only(df: pd.DataFrame, step: dict):
    # These tools just log findings and return the DF unchanged
    return df, {"status": "success", "details": {"info": "Metadata step evaluated"}}

def _action_standardize_boolean(df: pd.DataFrame, step: dict):
    column = step.get("column")
    if not column or column not in df.columns:
        return df, {"status": "error", "details": {"error": "Invalid column"}}
    
    df = df.copy()
    truthy = ['yes', 'y', 'true', 't', '1', '1.0']
    falsy = ['no', 'n', 'false', 'f', '0', '0.0']
    
    def map_bool(val):
        if pd.isna(val): return None
        s = str(val).strip().lower()
        if s in truthy: return True
        if s in falsy: return False
        return None
        
    df[column] = df[column].apply(map_bool)
    return df, {"status": "success", "details": {"column": column}}

def _action_normalize_phone(df: pd.DataFrame, step: dict):
    column = step.get("column")
    if not column or column not in df.columns:
        return df, {"status": "error", "details": {"error": "Invalid column"}}
        
    df = df.copy()
    def clean_phone(val):
        if pd.isna(val): return None
        s = str(val)
        # Strip negative signs if accidental (common in some exports)
        if s.startswith('-'): s = s[1:]
        # Strip non-digits
        digits = re.sub(r'\D', '', s)
        return digits if digits else None
        
    df[column] = df[column].apply(clean_phone)
    return df, {"status": "success", "details": {"column": column}}

def _action_map_values(df: pd.DataFrame, step: dict):
    column = step.get("column")
    mapping = step.get("mapping") # dict
    if not column or column not in df.columns or not isinstance(mapping, dict):
        return df, {"status": "error", "details": {"error": "Requires column and mapping dict"}}
        
    df = df.copy()
    df[column] = df[column].replace(mapping)
    return df, {"status": "success", "details": {"column": column, "mapped_keys": list(mapping.keys())}}

# Mapping
EXTENDED_HANDLERS = {
    "standardize_boolean": _action_standardize_boolean,
    "normalize_phone": _action_normalize_phone,
    "map_values": _action_map_values,
    "drop_missing_rows": _action_drop_missing_rows,
    "keep_latest_duplicate": _action_keep_latest_duplicate,
    "parse_datetime": _action_parse_datetime,
    "extract_year": _action_extract_year,
    "extract_month": _action_extract_month,
    "extract_day": _action_extract_day,
    "parse_currency": _action_parse_currency,
    "parse_height": _action_parse_height,
    "parse_weight": _action_parse_weight,
    "parse_percentage": _action_parse_percentage,
    "parse_rating": _action_parse_rating,
    "strip_special_characters": _action_strip_special_characters,
    "trim_whitespace": _action_trim_whitespace,
    "normalize_case": _action_normalize_case,
    "remove_line_breaks": _action_remove_line_breaks,
    "remove_non_ascii": _action_remove_non_ascii,
    "split_column": _action_split_column,
    "extract_pattern": _action_extract_pattern,
    "explode_array": _action_explode_array,
    "serialize_json": _action_serialize_json,
    "merge_columns": _action_merge_columns,
    "create_column": _action_create_column,
    "validate_email": _action_validate_email,
    "validate_phone": _action_validate_phone,
    "validate_postal_code": _action_validate_postal_code,
    "validate_country_code": _action_validate_country_code,
    "validate_uuid": _action_validate_uuid,
    "detect_outliers": _action_detect_outliers,
    "clip_outliers": _action_clip_outliers,
    "remove_outliers": _action_remove_outliers,
    "conditional_transform": _action_conditional_transform,
    "generate_surrogate_key": _action_generate_surrogate_key,
    "identify_primary_key": _action_metadata_only,
    "identify_foreign_keys": _action_metadata_only,
    "infer_relationships": _action_metadata_only,
    "schema_recommendation": _action_metadata_only,
}
