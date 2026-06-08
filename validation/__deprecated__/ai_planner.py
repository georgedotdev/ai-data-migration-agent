"""
AI Planning Layer

Interprets natural language migration requests using an LLM
and produces structured migration plans that drive the execution framework.

Supports multiple LLM providers:
- Google Gemini (recommended for demo)
- OpenAI GPT (backward compatible)
- Deterministic fallback (no LLM required)

Supports multi-connector planning:
- Source types: csv, postgresql, mongodb
- Target types: duckdb, postgresql, mongodb

When no API key is available, falls back to deterministic planning.

The generated plan directly influences:
- Which connectors are used (source_type, target_type)
- Whether a target file is auto-generated (generate_target)
- Whether connection details are required (requires_connection)
- Which transformations the executor applies
- Which validations the tester runs
"""

import json


# ─────────────────────────────────────────────
# Valid values for plan validation
# ─────────────────────────────────────────────

VALID_SOURCE_TYPES = {"csv", "postgresql", "mongodb"}
VALID_TARGET_TYPES = {"duckdb", "postgresql", "mongodb"}
VALID_TRANSFORMATIONS = {
    "normalize_columns", "handle_nulls", "type_conversion"
}
VALID_VALIDATIONS = {"row_count", "checksum"}


# ─────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────

def generate_plan(
    user_request,
    filename,
    schema,
    api_key=None,
    source_type_hint=None,
    target_type_hint=None,
    has_target_config=False,
    provider="auto"
):
    """
    Generate a structured migration plan from a natural language request.

    Args:
        user_request: Natural language migration request
        filename: Source filename or identifier
        schema: Discovered schema dict
        api_key: API key for LLM provider (optional)
        source_type_hint: Pre-selected source type from dashboard
        target_type_hint: Pre-selected target type from dashboard
        has_target_config: Whether target connection details are provided
        provider: LLM provider — 'gemini', 'openai', 'deterministic',
                  or 'auto' (default, routes to OpenAI for backward compat)

    Returns a dict with:
        source_type, target_type, table_name,
        transformations, validations, reasoning,
        planning_method, generate_target, requires_connection
    """

    # ─── Gemini provider ───
    if api_key and provider == "gemini":
        try:
            return _generate_gemini_plan(
                user_request, filename, schema, api_key,
                source_type_hint, target_type_hint,
                has_target_config
            )
        except Exception as e:
            print(f"[AI PLANNER] Gemini planning failed: {e}")
            print("[AI PLANNER] Falling back to deterministic")
            return _generate_deterministic_plan(
                user_request, filename, schema,
                source_type_hint, target_type_hint,
                has_target_config
            )

    # ─── OpenAI provider (also default for 'auto' with key) ───
    if api_key and provider in ("openai", "auto"):
        try:
            return _generate_ai_plan(
                user_request, filename, schema, api_key,
                source_type_hint, target_type_hint,
                has_target_config
            )
        except Exception as e:
            print(f"[AI PLANNER] LLM planning failed: {e}")
            print("[AI PLANNER] Falling back to deterministic")
            return _generate_deterministic_plan(
                user_request, filename, schema,
                source_type_hint, target_type_hint,
                has_target_config
            )

    # ─── No API key or deterministic provider ───
    print("[AI PLANNER] No API key — deterministic planning")
    return _generate_deterministic_plan(
        user_request, filename, schema,
        source_type_hint, target_type_hint,
        has_target_config
    )


# ─────────────────────────────────────────────
# Shared prompt builder
# ─────────────────────────────────────────────

def _build_planning_prompt(
    filename, schema, user_request,
    target_type_hint, has_target_config
):
    """Build the planning prompt used by all LLM planners."""

    schema_context = _format_schema(schema)

    target_context = ""
    if target_type_hint:
        target_context = (
            f"\nUser has pre-selected target type: "
            f"{target_type_hint}"
        )
        if has_target_config:
            target_context += (
                "\nTarget connection details have been provided."
            )
        else:
            target_context += (
                "\nNo target connection details provided yet."
            )

    return f"""You are a data migration planning agent. Interpret the user's
migration request and produce a structured migration plan.

AVAILABLE SOURCE TYPES:
- csv (CSV files)
- postgresql (PostgreSQL database tables)
- mongodb (MongoDB collections)

AVAILABLE TARGET TYPES:
- duckdb (DuckDB embedded database — can be auto-generated as a downloadable file)
- postgresql (PostgreSQL database — requires a running server with connection details)
- mongodb (MongoDB database — requires a running server with connection details)

AVAILABLE TRANSFORMATIONS (select which to apply):
- normalize_columns: Lowercase all column names, standardize naming
- handle_nulls: Fill nulls with defaults (strings→"UNKNOWN", floats→0.0, ints→0)
- type_conversion: Convert columns to correct types (e.g. revenue→float)

AVAILABLE VALIDATIONS (select which to run):
- row_count: Verify source and target row counts match
- checksum: SHA-256 checksum comparison of source and target data

SOURCE FILE/TABLE: {filename}
{target_context}

DISCOVERED SCHEMA:
{schema_context}

USER REQUEST: {user_request}

Respond with valid JSON in exactly this format:
{{
    "source_type": "<csv|postgresql|mongodb>",
    "target_type": "<duckdb|postgresql|mongodb>",
    "table_name": "<lowercase_underscored_name>",
    "generate_target": <true if target is duckdb and no existing file provided>,
    "requires_connection": <true if target is postgresql or mongodb and no connection details>,
    "transformations": ["<selected transformations>"],
    "validations": ["<selected validations>"],
    "reasoning": {{
        "source_type": "<why this source type>",
        "target_type": "<why this target type>",
        "target_mode": "<explain if file will be generated or if connection is required>",
        "table_name": "<why this table name>",
        "transformations": "<why these transformations>",
        "validations": "<why these validations>"
    }}
}}

Rules:
- table_name must be lowercase with underscores
- DuckDB targets can be auto-generated as downloadable files
- PostgreSQL and MongoDB targets ALWAYS require connection details
- If the user asks for PostgreSQL/MongoDB without providing details, set requires_connection to true
- Select transformations based on schema analysis and user request
- Always include both validations unless user asks to skip
- Provide clear, specific reasoning for every decision"""


# ─────────────────────────────────────────────
# Plan response validation
# ─────────────────────────────────────────────

def _validate_plan_response(plan):
    """
    Validate that an LLM-generated plan has all required fields
    with valid values. Sanitizes transformations and validations
    to only known values.

    Returns True if the plan is structurally valid.
    """

    if not isinstance(plan, dict):
        return False

    required = {
        "source_type", "target_type", "table_name",
        "transformations", "validations"
    }
    if not required.issubset(plan.keys()):
        return False

    if plan["source_type"] not in VALID_SOURCE_TYPES:
        return False
    if plan["target_type"] not in VALID_TARGET_TYPES:
        return False

    if not isinstance(plan["transformations"], list):
        return False
    if not isinstance(plan["validations"], list):
        return False

    # Sanitize to known values only
    plan["transformations"] = [
        t for t in plan["transformations"]
        if t in VALID_TRANSFORMATIONS
    ]
    plan["validations"] = [
        v for v in plan["validations"]
        if v in VALID_VALIDATIONS
    ]

    return True


# ─────────────────────────────────────────────
# Gemini Planner
# ─────────────────────────────────────────────

def _generate_gemini_plan(
    user_request, filename, schema, api_key,
    source_type_hint, target_type_hint,
    has_target_config
):
    """Generate plan using Google Gemini API."""

    from google import genai
    from google.genai import types
    print("***** GEMINI PLANNER USED *****")
    client = genai.Client(api_key=api_key)

    prompt = _build_planning_prompt(
        filename, schema, user_request,
        target_type_hint, has_target_config
    )

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            temperature=0,
            response_mime_type="application/json",
        )
    )

    plan = json.loads(response.text)

    # Validate response structure
    if not _validate_plan_response(plan):
        raise ValueError(
            "Gemini returned invalid plan structure"
        )

    plan["planning_method"] = "gemini"
    return plan


# ─────────────────────────────────────────────
# OpenAI Planner (preserved for backward compat)
# ─────────────────────────────────────────────

def _generate_ai_plan(
    user_request, filename, schema, api_key,
    source_type_hint, target_type_hint,
    has_target_config
):
    """Generate plan using OpenAI GPT via langchain-openai."""

    from langchain_openai import ChatOpenAI

    llm = ChatOpenAI(
        model="gpt-4o-mini",
        temperature=0,
        api_key=api_key,
        model_kwargs={
            "response_format": {"type": "json_object"}
        }
    )

    prompt = _build_planning_prompt(
        filename, schema, user_request,
        target_type_hint, has_target_config
    )

    response = llm.invoke(prompt)
    plan = json.loads(response.content)
    plan["planning_method"] = "ai"

    return plan


# ─────────────────────────────────────────────
# Deterministic Planner
# ─────────────────────────────────────────────

def _generate_deterministic_plan(
    user_request, filename, schema,
    source_type_hint=None, target_type_hint=None,
    has_target_config=False
):
    """Fallback deterministic planning — no LLM required."""
    print("***** DETERMINISTIC PLANNER USED *****")
    # Determine source type
    source_type = (source_type_hint or "csv").lower()

    # Determine target type
    target_type = (target_type_hint or "duckdb").lower()

    # Also try to detect target from user request
    request_lower = user_request.lower() if user_request else ""
    if "postgres" in request_lower:
        target_type = "postgresql"
    elif "mongo" in request_lower:
        target_type = "mongodb"
    elif "duckdb" in request_lower or "duck" in request_lower:
        target_type = "duckdb"

    # Derive table name
    table_name = (
        filename
        .replace(".csv", "")
        .replace(".CSV", "")
        .lower()
        .replace(" ", "_")
        .replace("-", "_")
    )

    # Target mode logic
    if target_type == "duckdb":
        generate_target = not has_target_config
        requires_connection = False
        target_mode_reason = (
            "DuckDB is a file-based database. "
            + (
                "A new .duckdb file will be generated "
                "and made available for download."
                if generate_target
                else "Writing to the provided DuckDB file."
            )
        )
    elif target_type in ("postgresql", "mongodb"):
        generate_target = False
        requires_connection = not has_target_config
        db_name = (
            "PostgreSQL" if target_type == "postgresql"
            else "MongoDB"
        )
        target_mode_reason = (
            f"{db_name} is a live database server. "
            + (
                f"Connection details are required to "
                f"migrate data into {db_name}."
                if requires_connection
                else f"Connection details provided — "
                f"ready to migrate into {db_name}."
            )
        )
    else:
        generate_target = False
        requires_connection = False
        target_mode_reason = "Unknown target type."

    # Analyze schema to decide transformations
    transformations = []
    transform_reasons = []

    columns = schema.get("columns", [])
    column_names = [c.get("name", "") for c in columns]

    # Check column casing
    has_uppercase = any(
        name != name.lower() for name in column_names
    )
    transformations.append("normalize_columns")
    if has_uppercase:
        transform_reasons.append(
            "Column names contain uppercase characters — "
            "normalization will standardize to lowercase"
        )
    else:
        transform_reasons.append(
            "Column normalization applied as standard practice"
        )

    # Check nullability
    has_nullables = any(
        c.get("nullable", False) for c in columns
    )
    transformations.append("handle_nulls")
    if has_nullables:
        transform_reasons.append(
            "Nullable columns detected — null handling will "
            "fill missing values with type-appropriate defaults"
        )
    else:
        transform_reasons.append(
            "Null handling applied preventively for data integrity"
        )

    # Type conversion
    transformations.append("type_conversion")
    transform_reasons.append(
        "Type conversion ensures numeric columns are stored "
        "with correct precision in the target"
    )

    # Full validation suite
    validations = ["row_count", "checksum"]

    return {
        "source_type": source_type,
        "target_type": target_type,
        "table_name": table_name,
        "generate_target": generate_target,
        "requires_connection": requires_connection,
        "transformations": transformations,
        "validations": validations,
        "planning_method": "deterministic",
        "reasoning": {
            "source_type": (
                f"Source type '{source_type}' detected from "
                f"context: {filename}"
            ),
            "target_type": (
                f"Target type '{target_type}' selected based "
                f"on user request"
            ),
            "target_mode": target_mode_reason,
            "table_name": (
                f"Table name '{table_name}' derived from "
                f"source identifier '{filename}'"
            ),
            "transformations": ". ".join(transform_reasons),
            "validations": (
                "Full validation suite applied — row count "
                "verification ensures no data loss, SHA-256 "
                "checksum ensures byte-level data integrity"
            )
        }
    }


def _format_schema(schema):
    """Format schema dict into readable text for the LLM prompt."""

    lines = []
    lines.append(
        f"Row Count: {schema.get('row_count', 'unknown')}"
    )
    lines.append(
        f"Column Count: {schema.get('column_count', 'unknown')}"
    )

    pk = schema.get("primary_key_candidates", [])
    lines.append(
        f"Primary Key Candidates: "
        f"{pk if pk else 'None detected'}"
    )

    lines.append("")
    lines.append("Columns:")

    for col in schema.get("columns", []):
        nullable = (
            "nullable" if col.get("nullable") else "not null"
        )
        unique = (
            "unique" if col.get("unique") else "not unique"
        )
        lines.append(
            f"  - {col.get('name')}: {col.get('dtype')} "
            f"({nullable}, {unique})"
        )

    return "\n".join(lines)
