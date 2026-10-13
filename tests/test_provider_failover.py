import pytest
from unittest.mock import patch, MagicMock
from ai_brain import generate_transformation_dsl

ALL_KEYS = {"Groq": "k", "Gemini": "k", "OpenAI": "k"}


@pytest.fixture
def sample_profile():
    return {
        "row_count": 100,
        "duplicate_rows": 0,
        "data_quality_score": 100.0,
        "columns": {}
    }

@patch("ai_brain.get_ai_provider")
def test_failover_chain_traversal(mock_get_provider, sample_profile):
    # Setup mock to always throw exception
    mock_provider = MagicMock()
    mock_provider.generate_plan.side_effect = Exception("Mock API Error")
    mock_get_provider.return_value = mock_provider
    
    # Run DSL generation
    dsl = generate_transformation_dsl(sample_profile, requested_provider="Auto", api_keys=ALL_KEYS)
    
    # Verify fallback to Deterministic
    assert dsl.get("planning_method") == "DeterministicProvider"
    metadata = dsl.get("_metadata", {})
    
    # Verify chain
    assert metadata.get("provider_used") == "Deterministic"
    assert metadata.get("fallback_used") is True
    chain = metadata.get("fallback_chain", [])
    # every model of every keyed provider is tried, in provider order, before the rule-based planner
    assert list(dict.fromkeys(chain)) == ["Groq", "Gemini", "OpenAI", "Deterministic"]
    assert chain.count("Gemini") == 3

@patch("ai_brain.get_ai_provider")
def test_specific_provider_failover(mock_get_provider, sample_profile):
    # Setup mock to fail specifically when Groq is requested
    mock_groq = MagicMock()
    mock_groq.generate_plan.side_effect = Exception("Groq Error")
    
    mock_gemini = MagicMock()
    mock_gemini.generate_plan.return_value = {"planning_method": "GeminiProvider", "transformations": []}
    
    def side_effect(provider_name, model_name, api_key=None):
        if provider_name == "Groq":
            return mock_groq
        return mock_gemini
        
    mock_get_provider.side_effect = side_effect
    
    # Run DSL generation starting with Groq
    dsl = generate_transformation_dsl(sample_profile, requested_provider="Groq", api_keys=ALL_KEYS)
    
    metadata = dsl.get("_metadata", {})
    assert metadata.get("provider_used") == "Gemini"
    assert metadata.get("fallback_used") is True
    chain = metadata.get("fallback_chain", [])
    assert list(dict.fromkeys(chain)) == ["Groq", "Gemini"]


@patch("ai_brain.get_ai_provider")
def test_providers_without_keys_are_skipped(mock_get_provider, sample_profile, monkeypatch):
    for var in ("GROQ_API_KEY", "GOOGLE_API_KEY", "GEMINI_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(var, raising=False)
    mock = MagicMock()
    mock.generate_plan.return_value = {"planning_method": "GeminiProvider", "transformations": []}
    mock_get_provider.return_value = mock
    dsl = generate_transformation_dsl(sample_profile, requested_provider="Auto", api_keys={"Gemini": "k"})
    assert {c.args[0] for c in mock_get_provider.call_args_list} == {"Gemini"}
    assert dsl["_metadata"]["provider_used"] == "Gemini"
