import pytest
import os
from unittest.mock import patch, MagicMock

from ai_brain import (
    generate_transformation_dsl,
    summarize_transformation_dsl,
    DeterministicProvider,
    GeminiProvider,
    OpenAIProvider,
    get_ai_provider
)

# ─────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────

@pytest.fixture
def sample_profile():
    return {
        "row_count": 100,
        "duplicate_rows": 2,
        "data_quality_score": 85.0,
        "columns": {
            "First Name": {
                "dtype": "object",
                "missing_count": 10,
                "missing_pct": 10.0,
                "structural_type": "flat",
                "sample_values": ["Alice", "Bob"]
            },
            "Revenue": {
                "dtype": "float64",
                "missing_count": 0,
                "missing_pct": 0.0,
                "structural_type": "flat",
                "sample_values": [100.0, 200.0]
            },
            "Address": {
                "dtype": "object",
                "missing_count": 0,
                "missing_pct": 0.0,
                "structural_type": "nested_object",
                "sample_values": [{"street": "123 Main St"}]
            }
        }
    }

# ─────────────────────────────────────────────
# Provider Selection Tests
# ─────────────────────────────────────────────

@patch.dict(os.environ, {"GOOGLE_API_KEY": "dummy", "OPENAI_API_KEY": ""})
def test_get_ai_provider_gemini():
    provider = get_ai_provider()
    assert isinstance(provider, GeminiProvider)


@patch.dict(os.environ, {"OPENAI_API_KEY": "dummy", "GOOGLE_API_KEY": ""})
def test_get_ai_provider_openai():
    provider = get_ai_provider()
    assert isinstance(provider, OpenAIProvider)


@patch.dict(os.environ, {"GOOGLE_API_KEY": "", "OPENAI_API_KEY": ""})
def test_get_ai_provider_deterministic():
    provider = get_ai_provider()
    assert isinstance(provider, DeterministicProvider)


# ─────────────────────────────────────────────
# Deterministic Provider Tests
# ─────────────────────────────────────────────

def test_deterministic_provider_logic(sample_profile):
    provider = DeterministicProvider()
    dsl = provider.generate_plan(sample_profile, user_request=None, normalize_columns=True)

    assert dsl["planning_method"] == "DeterministicProvider"
    actions = [step["action"] for step in dsl["transformations"]]

    # Normalize should be first
    assert actions[0] == "normalize_columns"
    
    # Check for flatten_object for Address
    assert "flatten_object" in actions
    
    # Check for remove_duplicates due to duplicate_rows=2
    assert "remove_duplicates" in actions
    
    # Check for fill_missing for First Name
    assert "fill_missing" in actions

    # Reasoning should match steps
    assert len(dsl["reasoning"]) == len(dsl["transformations"])


# ─────────────────────────────────────────────
# Fallback Tests
# ─────────────────────────────────────────────

@patch("ai_brain.get_ai_provider")
def test_generate_transformation_dsl_fallback(mock_get_provider, sample_profile):
    """If primary LLM fails, it should fallback to deterministic."""
    mock_llm_provider = MagicMock()
    mock_llm_provider.generate_plan.side_effect = Exception("API Error")
    mock_llm_provider.__class__.__name__ = "OpenAIProvider"
    
    mock_get_provider.return_value = mock_llm_provider

    # Call it without API keys, but the mock returns the failing LLM
    dsl = generate_transformation_dsl(sample_profile)
    assert dsl["planning_method"] == "DeterministicProvider"


# ─────────────────────────────────────────────
# Summary Tests
# ─────────────────────────────────────────────

def test_summarize_transformation_dsl():
    dsl = {
        "transformations": [
            {"action": "normalize_columns"},
            {"action": "fill_missing"},
            {"action": "cast_type"},
            {"action": "flatten_object"},
            {"action": "drop_column"}
        ]
    }
    labels = summarize_transformation_dsl(dsl)
    
    # Legacy labels mapping
    assert "normalize_columns" in labels
    assert "handle_nulls" in labels
    assert "type_conversion" in labels
    
    # New labels pass-through
    assert "flatten_object" in labels
    assert "drop_column" in labels
