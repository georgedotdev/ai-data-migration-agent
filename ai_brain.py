"""
AI Brain for Transformation Planning

Consumes profiler output and generates an executable Transformation DSL plan.

Implements an LLM-backed Migration Assessment Agent using LangChain and Pydantic.
Supports Gemini (primary), OpenAI, and a Deterministic fallback.
"""

import os
from dotenv import load_dotenv
load_dotenv()

import re
import json
from abc import ABC, abstractmethod
from typing import Any, Optional

from pydantic import BaseModel, Field, ConfigDict, field_validator

from etl.dsl_engine import validate_dsl

# ─────────────────────────────────────────────
# Pydantic Schemas for Structured Output
# ─────────────────────────────────────────────

class DSLStep(BaseModel):
    model_config = ConfigDict(extra='ignore')

    action: str = Field(description="The DSL action name (e.g., fill_missing, parse_currency, extract_year, flatten_object, etc.)")
    column: Optional[str] = Field(default=None, description="The target column name")
    value: Optional[Any] = Field(default=None, description="The fallback/fill value")
    target_type: Optional[str] = Field(default=None, description="The target data type for cast_type")
    new_name: Optional[str] = Field(default=None, description="The new column name")
    prefix: Optional[str] = Field(default=None, description="The prefix for flatten_object")
    strategy: Optional[str] = Field(default=None, description="Strategy for fill_missing (mean, median, mode, constant, forward_fill, backward_fill)")
    confidence: int = Field(default=100, description="Confidence score of this action (0-100). E.g. 95")
    condition: Optional[str] = Field(default=None, description="Condition string for conditional_transform")
    operation: Optional[str] = Field(default=None, description="Operation string for conditional_transform")
    delimiter: Optional[str] = Field(default=None, description="Delimiter for split_column")
    regex: Optional[str] = Field(default=None, description="Regex pattern for extract_pattern or split_column")
    mapping: Optional[dict] = Field(default=None, description="Dictionary mapping for map_values action (e.g. {'Old': 'New'})")

    @field_validator('regex')
    @classmethod
    def validate_regex_length(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and len(v) > 500:
            raise ValueError("Regex pattern exceeds 500 characters maximum length limit.")
        return v
        
    @field_validator('column')
    @classmethod
    def validate_column(cls, v: Optional[str]) -> Optional[str]:
        if not v:
            return v
            
        v = v.strip().strip('"').strip("'")
        
        if len(v) == 0:
            raise ValueError("Column name cannot be empty or just quotes.")
            
        return v


class MigrationAssessment(BaseModel):
    model_config = ConfigDict(extra='ignore')

    dataset_assessment: str = Field(description="Overall health and risk assessment of the dataset")
    identified_issues: list[str] = Field(description="Specific data quality issues found in the profile")
    schema_mapping_recommendations: list[str] = Field(description="Recommendations for mapping source schema to target")
    recommended_transformations: list[DSLStep] = Field(description="The sequence of deterministic DSL transformation steps")
    reasoning: list[dict] = Field(description="Reasoning for each transformation step (list of dicts with 'step' index and 'reason' string)")


# ─────────────────────────────────────────────
# Provider Interface
# ─────────────────────────────────────────────

class AIProvider(ABC):
    @abstractmethod
    def generate_plan(self, profile: dict, user_request: str | None, normalize_columns: bool) -> dict:
        """Generate the transformation DSL plan."""
        pass


# ─────────────────────────────────────────────
# LLM Providers
# ─────────────────────────────────────────────

class BaseLLMProvider(AIProvider):
    def __init__(self, llm):
        self.llm = llm.with_structured_output(MigrationAssessment, include_raw=True)

    def _recover_assessment(self, raw_json: dict) -> MigrationAssessment:
        print("[AI Brain] ⚠️ Attempting partial recovery of MigrationAssessment...")
        reasoning = raw_json.get("reasoning", [])
        valid_reasoning = []
        
        assessment_kwargs = {
            "dataset_assessment": raw_json.get("dataset_assessment", "Fallback Assessment"),
            "identified_issues": raw_json.get("identified_issues", []),
            "schema_mapping_recommendations": raw_json.get("schema_mapping_recommendations", []),
            "reasoning": valid_reasoning,
            "recommended_transformations": []
        }
        
        raw_steps = raw_json.get("recommended_transformations", [])
        for i, step in enumerate(raw_steps):
            try:
                valid_step = DSLStep.model_validate(step)
                assessment_kwargs["recommended_transformations"].append(valid_step)
                # Keep the corresponding reasoning step if it exists
                if i < len(reasoning):
                    valid_reasoning.append(reasoning[i])
            except Exception as e:
                print(f"[AI Brain] ❌ Dropping Step {i} due to validation error: {e}")
                
        return MigrationAssessment.model_validate(assessment_kwargs)

    def generate_plan(self, profile: dict, user_request: str | None, normalize_columns: bool) -> dict:
        prompt = self._build_prompt(profile, user_request, normalize_columns)
        
        try:
            response = self.llm.invoke(prompt)
        except Exception as e:
            error_str = str(e)
            
            # Special handling for Groq's tool_use_failed which buries the generated JSON in the error message string
            idx = error_str.find("'failed_generation':")
            if idx != -1:
                start_quote = error_str.find("'", idx + 20)
                if start_quote != -1:
                    end_quote = error_str.find("'}", start_quote)
                    if end_quote != -1:
                        failed_gen = error_str[start_quote+1:end_quote]
                        start_idx = failed_gen.find('{')
                        if start_idx != -1:
                            raw_content = failed_gen[start_idx:]
                            raw_content = raw_content.replace("\\'", "'")
                            try:
                                raw_json = json.loads(raw_content)
                                print(f"[AI Brain] ⚠️ Recovered JSON from failed tool call exception.")
                                parsed = self._recover_assessment(raw_json)
                                assessment = parsed
                                transformations = []
                                for step in assessment.recommended_transformations:
                                    step_dict = {k: v for k, v in step.model_dump().items() if v is not None}
                                    transformations.append(step_dict)
                                dsl = {
                                    "dataset_assessment": assessment.dataset_assessment,
                                    "identified_issues": assessment.identified_issues,
                                    "schema_mapping_recommendations": assessment.schema_mapping_recommendations,
                                    "transformations": transformations,
                                    "reasoning": assessment.reasoning,
                                    "planning_method": self.__class__.__name__,
                                    "raw_prompt": prompt,
                                    "raw_ai_response": error_str
                                }
                                if normalize_columns:
                                    has_normalize = any(t.get("action") == "normalize_columns" for t in transformations)
                                    if not has_normalize:
                                        transformations.insert(0, {"action": "normalize_columns"})
                                        dsl["reasoning"].insert(0, {"step": 0, "reason": "Standardizing column names automatically."})
                                        for i in range(1, len(dsl["reasoning"])):
                                            if "step" in dsl["reasoning"][i]:
                                                dsl["reasoning"][i]["step"] += 1
                                is_valid, errors = validate_dsl(dsl)
                                if not is_valid:
                                    raise ValueError(f"LLM generated invalid transformation DSL: {errors}")
                                return dsl
                            except json.JSONDecodeError:
                                pass
            
            raise RuntimeError(f"LLM generation failed completely: {e}")

        parsing_error = response.get("parsing_error")
        parsed = response.get("parsed")
        raw = response.get("raw")

        if parsing_error or not parsed:
            print(f"[AI Brain] ⚠️ Pydantic Validation Error: {parsing_error}")
            try:
                # Extract the tool arguments (LangChain usually places these in tool_calls for GenAI/OpenAI)
                if hasattr(raw, "tool_calls") and raw.tool_calls:
                    raw_json = raw.tool_calls[0]["args"]
                else:
                    # Fallback if returned as JSON string block
                    raw_content = raw.content if hasattr(raw, "content") else str(raw)
                    raw_content = raw_content.strip()
                    if raw_content.startswith("```json"):
                        raw_content = raw_content[7:-3].strip()
                    raw_json = json.loads(raw_content)

                print(f"[AI Brain] ⚠️ Raw JSON payload: {json.dumps(raw_json)}")
                
                parsed = self._recover_assessment(raw_json)
            except Exception as recovery_error:
                raise RuntimeError(f"LLM generation failed: {parsing_error}. Recovery also failed: {recovery_error}")

        assessment = parsed

        # Convert Pydantic model to dictionary
        transformations = []
        for step in assessment.recommended_transformations:
            step_dict = {k: v for k, v in step.model_dump().items() if v is not None}
            transformations.append(step_dict)

        raw_content = ""
        if raw:
            if hasattr(raw, "content") and raw.content:
                raw_content = str(raw.content)
            elif hasattr(raw, "tool_calls") and raw.tool_calls:
                raw_content = json.dumps(raw.tool_calls, indent=2)
            else:
                raw_content = str(raw)

        dsl = {
            "dataset_assessment": assessment.dataset_assessment,
            "identified_issues": assessment.identified_issues,
            "schema_mapping_recommendations": assessment.schema_mapping_recommendations,
            "transformations": transformations,
            "reasoning": assessment.reasoning,
            "planning_method": self.__class__.__name__,
            "raw_prompt": prompt,
            "raw_ai_response": raw_content
        }

        # Automatically insert normalize_columns if requested and not present
        if normalize_columns:
            has_normalize = any(t.get("action") == "normalize_columns" for t in transformations)
            if not has_normalize:
                transformations.insert(0, {"action": "normalize_columns"})
                dsl["reasoning"].insert(0, {"step": 0, "reason": "Standardizing column names automatically."})
                # shift reasoning steps
                for i in range(1, len(dsl["reasoning"])):
                    if "step" in dsl["reasoning"][i]:
                        dsl["reasoning"][i]["step"] += 1

        is_valid, errors = validate_dsl(dsl)
        if not is_valid:
            raise ValueError(f"LLM generated invalid transformation DSL: {errors}")

        return dsl

    def _build_prompt(self, profile: dict, user_request: str | None, normalize_columns: bool) -> str:
        # Strip some heavy things from profile like large sample values to save tokens
        clean_profile = {}
        for col, data in profile.get("columns", {}).items():
            clean_data = data.copy()
            if "sample_values" in clean_data:
                clean_data["sample_values"] = clean_data["sample_values"][:3]
            clean_profile[col] = clean_data

        profile_json = json.dumps(clean_profile, indent=2)

        prompt = f"""
        You are an expert Data Migration AI. Your job is to analyze the data profile and recommend a sequence of transformation steps using a specific DSL.

        ## Data Profile
        Row Count: {profile.get("row_count")}
        Duplicates: {profile.get("duplicate_rows")}
        Quality Score: {profile.get("data_quality_score")}

        Columns:
        {profile_json}

        ## User Request
        {user_request or "No specific request. Perform a safe and comprehensive standard migration."}

        ## Instructions
        1. Assess the dataset health.
        2. Identify data quality issues (nulls, nested objects, duplicates, wrong types).
        3. Provide schema mapping recommendations.
        4. Recommend a strict sequence of DSL transformations to fix the issues.
        5. Provide reasoning for each step.
        
        # CORE DESIGN PRINCIPLE
        1. Preserve data whenever possible.
        2. Dropping columns should be a LAST RESORT.
        3. Prefer cleansing actions like parse_currency, parse_datetime, fill_missing over drop_column.
        4. CRITICAL: You MUST explicitly schedule a `fill_missing` action (with an appropriate strategy like mean, median, or mode) for EVERY SINGLE column that has missing values. Do not leave any missing values unresolved. NEVER use drop_missing_rows.
        5. CRITICAL: If a column with missing values also requires parsing (e.g., `parse_currency`, `parse_datetime`, `standardize_boolean`), you MUST schedule the parsing action FIRST, and then explicitly schedule a separate `fill_missing` action for that SAME column afterwards.
        7. CRITICAL: If a column contains percentages (e.g., '84%', '12%'), you MUST use `parse_percentage`.
        8. CRITICAL: If a categorical column (like gender) has inconsistent casing or abbreviations (e.g., 'M', 'Male', 'm'), you MUST use `normalize_case` or `map_values`.
        9. CRITICAL: Schema mappings must preserve semantic meaning. Reject mappings that change data meaning (e.g. Age != Birth Year).
        10. CRITICAL: Duplicates in categorical/dimension columns (e.g., gender, skill, language) are NORMAL. DO NOT use remove_duplicates on them just because their duplicate_count is high. ONLY use remove_duplicates on unique identifiers (e.g., ID, Email).
        11. CRITICAL: When using `fill_missing`, you MUST specify either the `strategy` field (e.g., mean, median, mode) OR the `value` field if using a constant.
        12. CRITICAL: When using `cast_type`, you MUST specify the `target_type` field (e.g., int64, float64, str, bool, datetime, category).
        13. CRITICAL SEQUENCING RULE: You MUST schedule `fill_missing` BEFORE `cast_type: int64` on the same column. Pandas int64 cannot hold NaN values. If you cast before filling, the step will crash. The correct order is: parse → fill_missing → cast_type.
        14. CRITICAL: When using `keep_latest_duplicate`, you MUST provide both `column` (the dedup key) AND `timestamp_column` (the datetime column used to determine which record is "latest").
        15. CRITICAL: If a categorical column has inconsistent casing across its values (e.g., "Electronics", "ELECTRONICS", "electronic"), you MUST schedule `normalize_case` for that column. Check the sample_values carefully for mixed casing.
        16. CRITICAL: When `parse_currency` or `cast_type` converts unparseable text values (like "abd" or "four hundred") to NaN, be aware this is DATA LOSS. Flag it in your identified_issues.

        Available DSL Actions include:
        - Cat 1: fill_missing (strategies: mean, median, mode, constant, forward_fill, backward_fill), drop_missing_rows
        - Cat 2: remove_duplicates, keep_latest_duplicate
        - Cat 3: cast_type (int64, float64, str, datetime, bool, category)
        - Cat 4: parse_datetime, extract_year, extract_month, extract_day
        - Cat 5: parse_currency (e.g., €67.5M -> 67500000)
        - Cat 6: parse_height, parse_weight
        - Cat 7: parse_percentage
        - Cat 8: parse_rating
        - Cat 9: strip_special_characters, trim_whitespace, normalize_case, remove_line_breaks, remove_non_ascii
        - Cat 10: split_column
        - Cat 11: extract_pattern
        - Cat 12: flatten_object, explode_array, serialize_json
        - Cat 13: rename_column, merge_columns, drop_column, create_column
        - Cat 14: validate_email, validate_phone, validate_postal_code, validate_country_code, validate_uuid
        - Cat 15: detect_outliers, clip_outliers, remove_outliers
        - Cat 16: conditional_transform
        - Cat 17: generate_surrogate_key, identify_primary_key, identify_foreign_keys, infer_relationships, schema_recommendation

        For each DSL Action you recommend, you MUST provide a confidence score (0-100) and an exact, explainable reason in the reasoning array.
        """
        return prompt


class GeminiProvider(BaseLLMProvider):
    def __init__(self, model: str = "gemini-2.5-flash"):
        from langchain_google_genai import ChatGoogleGenerativeAI
        print(f"[AI Brain] Initializing GeminiProvider with model: {model}")
        llm = ChatGoogleGenerativeAI(model=model, temperature=0.0)
        super().__init__(llm)


class OpenAIProvider(BaseLLMProvider):
    def __init__(self, model: str = "gpt-4o"):
        from langchain_openai import ChatOpenAI
        print(f"[AI Brain] Initializing OpenAIProvider with model: {model}")
        llm = ChatOpenAI(model=model, temperature=0.0)
        super().__init__(llm)


class GroqProvider(BaseLLMProvider):
    def __init__(self, model: str = "llama-3.3-70b-versatile"):
        from langchain_groq import ChatGroq
        print(f"[AI Brain] Initializing GroqProvider with model: {model}")
        llm = ChatGroq(model=model, temperature=0.0)
        super().__init__(llm)


# ─────────────────────────────────────────────
# Deterministic Provider (Fallback)
# ─────────────────────────────────────────────

class DeterministicProvider(AIProvider):
    def generate_plan(self, profile: dict, user_request: str | None, normalize_columns: bool) -> dict:
        columns = profile.get("columns") or {}
        request = (user_request or "").lower()

        transformations: list[dict[str, Any]] = []
        reasoning: list[dict[str, Any]] = []
        warnings: list[str] = []

        normalized_names = {
            original: self._normalize_column_name(original)
            for original in columns.keys()
        }
        needs_normalization = any(
            original != normalized
            for original, normalized in normalized_names.items()
        )

        if normalize_columns and needs_normalization:
            self._append_step(
                transformations,
                reasoning,
                {"action": "normalize_columns"},
                "Column names are standardized before later DSL steps so column references are stable.",
            )

        def effective_name(column_name: str) -> str:
            if normalize_columns and needs_normalization:
                return normalized_names[column_name]
            return column_name

        for column_name, col_profile in columns.items():
            structural_type = col_profile.get("structural_type", "flat")
            column_ref = effective_name(column_name)

            if structural_type == "nested_object":
                prefix = f"{column_ref}_"
                self._append_step(
                    transformations,
                    reasoning,
                    {
                        "action": "flatten_object",
                        "column": column_ref,
                        "prefix": prefix,
                    },
                    (
                        f"Column '{column_name}' contains nested objects; flattening creates "
                        "relational columns for cross-database migration."
                    ),
                )
            elif structural_type == "nested_array":
                warnings.append(
                    f"Column '{column_name}' contains arrays, but the current DSL has no array "
                    "serialization or explode action. It is left unchanged."
                )

        if profile.get("duplicate_rows", 0) > 0:
            self._append_step(
                transformations,
                reasoning,
                {"action": "remove_duplicates"},
                "Fully duplicated rows were detected in the profile and can be removed deterministically.",
            )

        for column_name, col_profile in columns.items():
            missing_count = col_profile.get("missing_count", 0)
            if missing_count <= 0:
                continue

            if col_profile.get("structural_type") != "flat":
                warnings.append(
                    f"Column '{column_name}' has missing values but is nested; null filling is skipped "
                    "until after a richer nested-field profile is available."
                )
                continue

            fill_value = self._default_fill_value(col_profile)
            self._append_step(
                transformations,
                reasoning,
                {
                    "action": "fill_missing",
                    "column": effective_name(column_name),
                    "value": fill_value,
                },
                (
                    f"Column '{column_name}' has {missing_count} missing values; "
                    f"using a type-aware default preserves row count for validation."
                ),
            )

        for column_name, col_profile in columns.items():
            target_type = self._recommended_cast_type(column_name, col_profile, request)
            if target_type is None:
                continue

            self._append_step(
                transformations,
                reasoning,
                {
                    "action": "cast_type",
                    "column": effective_name(column_name),
                    "target_type": target_type,
                },
                (
                    f"Column '{column_name}' is profiled as {col_profile.get('dtype')}; "
                    f"casting to {target_type} improves target schema consistency."
                ),
            )

        dsl = {
            "dataset_assessment": "Deterministic Assessment: Analyzed column types and null counts.",
            "identified_issues": [f"Missing values or structural issues detected by deterministic rules."],
            "schema_mapping_recommendations": ["Use default deterministic mappings."],
            "transformations": transformations,
            "reasoning": reasoning,
            "warnings": warnings,
            "planning_method": "DeterministicProvider",
        }

        is_valid, errors = validate_dsl(dsl)
        if not is_valid:
            raise ValueError(f"Generated invalid transformation DSL: {errors}")

        return dsl

    def _append_step(
        self,
        transformations: list[dict[str, Any]],
        reasoning: list[dict[str, Any]],
        step: dict[str, Any],
        reason: str,
    ) -> None:
        transformations.append(step)
        reasoning.append({
            "step": len(transformations) - 1,
            "action": step.get("action"),
            "reason": reason,
        })

    def _normalize_column_name(self, column_name: str) -> str:
        normalized = column_name.strip().lower()
        normalized = re.sub(r"[^a-z0-9_]", "_", normalized)
        normalized = re.sub(r"_+", "_", normalized)
        return normalized.strip("_")

    def _default_fill_value(self, col_profile: dict) -> Any:
        dtype = str(col_profile.get("dtype", "")).lower()

        if "bool" in dtype:
            return False
        if "int" in dtype:
            return 0
        if "float" in dtype or "double" in dtype or "decimal" in dtype:
            return 0.0
        if "datetime" in dtype or "date" in dtype:
            return "1970-01-01"
        return "UNKNOWN"

    def _recommended_cast_type(
        self,
        column_name: str,
        col_profile: dict,
        request: str,
    ) -> str | None:
        dtype = str(col_profile.get("dtype", "")).lower()
        name = column_name.lower()

        if "datetime" in dtype:
            return "datetime"
        if "float" in dtype or "double" in dtype or "decimal" in dtype:
            return "float64"
        if "int" in dtype:
            return "int64"

        sample_values = col_profile.get("sample_values") or []

        if self._looks_like_datetime_column(name, sample_values):
            return "datetime"

        if (
            "type" in request
            or "cast" in request
            or name in {"revenue", "amount", "price", "total", "score"}
        ) and self._samples_are_numeric(sample_values):
            return "float64"

        return None

    def _samples_are_numeric(self, sample_values: list[Any]) -> bool:
        non_empty = [
            value for value in sample_values
            if value not in (None, "")
        ]
        if not non_empty:
            return False

        for value in non_empty:
            try:
                float(value)
            except (TypeError, ValueError):
                return False
        return True

    def _looks_like_datetime_column(
        self,
        column_name: str,
        sample_values: list[Any],
    ) -> bool:
        if not any(token in column_name for token in ("date", "time", "created", "updated")):
            return False

        non_empty = [
            str(value) for value in sample_values
            if value not in (None, "")
        ]
        if not non_empty:
            return False

        date_like = re.compile(r"^\d{4}-\d{1,2}-\d{1,2}")
        return any(date_like.match(value) for value in non_empty)


# ─────────────────────────────────────────────
# Factory and Entry Point
# ─────────────────────────────────────────────

def get_ai_provider(provider_name: str, model_name: str) -> AIProvider:
    if provider_name == "Groq":
        return GroqProvider(model=model_name)
    elif provider_name == "Gemini":
        return GeminiProvider(model=model_name)
    elif provider_name == "OpenAI":
        return OpenAIProvider(model=model_name)
    else:
        return DeterministicProvider()


def generate_transformation_dsl(
    profile: dict,
    user_request: str | None = None,
    normalize_columns: bool = True,
    requested_provider: str = "Auto",
    requested_model: str = ""
) -> dict:
    """
    Build an executable DSL plan from a data profile using the best available provider.
    Implements a failover chain to ensure robust execution.
    """
    DEFAULT_CHAIN = [
        ("Groq", "llama-3.3-70b-versatile"),
        ("Gemini", "gemini-2.5-flash"),
        ("OpenAI", "gpt-4o"),
    ]
    
    chain_traversed = []
    providers_to_try = []
    
    if requested_provider != "Auto" and requested_provider != "Deterministic":
        providers_to_try.append((requested_provider, requested_model))
        
    for p, m in DEFAULT_CHAIN:
        if p != requested_provider:
            providers_to_try.append((p, m))

    if requested_provider == "Deterministic":
        providers_to_try = []

    for provider_name, model_name in providers_to_try:
        chain_traversed.append(provider_name)
        try:
            print(f"[AI Brain] Attempting {provider_name} with {model_name}...")
            provider = get_ai_provider(provider_name, model_name)
            result = provider.generate_plan(profile, user_request, normalize_columns)
            
            result["_metadata"] = {
                "provider_used": provider_name,
                "model_used": model_name,
                "fallback_chain": chain_traversed,
                "fallback_used": len(chain_traversed) > 1 or requested_provider == "Auto"
            }
            print(f"[AI Brain] OK - {provider_name} succeeded.")
            return result
        except UnicodeEncodeError as e:
            print(f"[AI Brain] CRITICAL FAIL - Encoding error: {e}")
            raise e
        except Exception as e:
            print(f"[AI Brain] FAIL - {provider_name} failed: {e}")
            continue

    if requested_provider != "Auto" and requested_provider != "Deterministic":
        raise RuntimeError(f"Requested provider {requested_provider} failed: {chain_traversed}")

    print("[AI Brain] Falling back to DeterministicProvider...")
    fallback = DeterministicProvider()
    fallback_dsl = fallback.generate_plan(profile, user_request, normalize_columns)
    fallback_dsl["fallback_reason"] = "All AI providers failed or Deterministic selected."
    chain_traversed.append("Deterministic")
    
    fallback_dsl["_metadata"] = {
        "provider_used": "Deterministic",
        "model_used": "N/A",
        "fallback_chain": chain_traversed,
        "fallback_used": requested_provider != "Deterministic"
    }
    return fallback_dsl


def summarize_transformation_dsl(dsl: dict) -> list[str]:
    """Return legacy transformation labels represented by a DSL plan."""
    actions = [
        step.get("action")
        for step in dsl.get("transformations", [])
        if isinstance(step, dict)
    ]

    labels: list[str] = []
    if "normalize_columns" in actions:
        labels.append("normalize_columns")
    if "fill_missing" in actions:
        labels.append("handle_nulls")
    if "cast_type" in actions:
        labels.append("type_conversion")

    for action in actions:
        if action not in {
            "normalize_columns",
            "fill_missing",
            "cast_type",
        } and action not in labels:
            labels.append(action)

    return labels
