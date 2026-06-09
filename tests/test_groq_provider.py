import pytest
from unittest.mock import patch, MagicMock
from ai_brain import GroqProvider

@pytest.fixture
def sample_profile():
    return {
        "row_count": 100,
        "duplicate_rows": 0,
        "data_quality_score": 100.0,
        "columns": {}
    }

@patch("langchain_groq.ChatGroq")
def test_groq_provider_initialization(mock_chat_groq):
    provider = GroqProvider(model="llama-3.3-70b-versatile")
    mock_chat_groq.assert_called_once_with(model="llama-3.3-70b-versatile", temperature=0.0)

@patch("langchain_groq.ChatGroq")
def test_groq_provider_generate_plan(mock_chat_groq, sample_profile):
    # Mock the structured output
    mock_llm_instance = MagicMock()
    mock_structured = MagicMock()
    
    # Mocking the structured output response format from LangChain
    mock_assessment = MagicMock()
    mock_assessment.dict.return_value = {
        "dataset_assessment": "Good",
        "identified_issues": [],
        "schema_mapping_recommendations": [],
        "recommended_transformations": [],
        "reasoning": []
    }
    
    mock_structured.invoke.return_value = {"parsed": mock_assessment}
    mock_llm_instance.with_structured_output.return_value = mock_structured
    mock_chat_groq.return_value = mock_llm_instance
    
    provider = GroqProvider()
    
    # Ensure no network call by mocking
    plan = provider.generate_plan(sample_profile, user_request=None, normalize_columns=False)
    
    assert plan["planning_method"] == "GroqProvider"
    assert "dataset_assessment" in plan
