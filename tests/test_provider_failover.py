import pytest
from unittest.mock import patch, MagicMock
from ai_brain import generate_transformation_dsl

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
    dsl = generate_transformation_dsl(sample_profile, requested_provider="Auto")
    
    # Verify fallback to Deterministic
    assert dsl.get("planning_method") == "DeterministicProvider"
    metadata = dsl.get("_metadata", {})
    
    # Verify chain
    assert metadata.get("provider_used") == "Deterministic"
    assert metadata.get("fallback_used") is True
    chain = metadata.get("fallback_chain", [])
    assert chain == ["Groq", "Gemini", "OpenAI", "Deterministic"]

@patch("ai_brain.get_ai_provider")
def test_specific_provider_failover(mock_get_provider, sample_profile):
    # Setup mock to fail specifically when Groq is requested
    mock_groq = MagicMock()
    mock_groq.generate_plan.side_effect = Exception("Groq Error")
    
    mock_gemini = MagicMock()
    mock_gemini.generate_plan.return_value = {"planning_method": "GeminiProvider", "transformations": []}
    
    def side_effect(provider_name, model_name):
        if provider_name == "Groq":
            return mock_groq
        return mock_gemini
        
    mock_get_provider.side_effect = side_effect
    
    # Run DSL generation starting with Groq
    dsl = generate_transformation_dsl(sample_profile, requested_provider="Groq")
    
    metadata = dsl.get("_metadata", {})
    assert metadata.get("provider_used") == "Gemini"
    assert metadata.get("fallback_used") is True
    chain = metadata.get("fallback_chain", [])
    assert chain == ["Groq", "Gemini"]
