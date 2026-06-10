import pytest
import json
from unittest.mock import MagicMock
from langchain_core.messages import AIMessage
from pydantic import ValidationError

from ai_brain import BaseLLMProvider, DSLStep, MigrationAssessment

class DummyLLM:
    def __init__(self, response_dict):
        self.response_dict = response_dict

    def with_structured_output(self, schema, include_raw=False):
        return self

    def invoke(self, prompt):
        return self.response_dict


def test_parsing_recovery_drops_oversized_regex():
    # Setup raw JSON with one valid step and one invalid oversized regex step
    oversized_regex = "a" * 501
    
    raw_args = {
        "dataset_assessment": "Test dataset is mostly healthy.",
        "identified_issues": [],
        "schema_mapping_recommendations": [],
        "reasoning": [
            {"step": 0, "reason": "Good step"},
            {"step": 1, "reason": "Bad regex step"}
        ],
        "recommended_transformations": [
            {"action": "remove_duplicates", "confidence": 90},
            {"action": "extract_pattern", "column": "email", "regex": oversized_regex, "confidence": 50}
        ]
    }
    
    # Langchain mock structure when include_raw=True
    mock_response = {
        "raw": AIMessage(
            content="",
            tool_calls=[{"name": "MigrationAssessment", "args": raw_args, "id": "call_1"}]
        ),
        "parsed": None,
        "parsing_error": ValidationError.from_exception_data("title", line_errors=[])
    }
    
    provider = BaseLLMProvider(DummyLLM(mock_response))
    
    # generate_plan handles the prompt building internally, so we mock it
    provider._build_prompt = MagicMock(return_value="dummy prompt")
    
    # generate_plan parses the response
    dsl_output = provider.generate_plan(profile={}, user_request=None, normalize_columns=False)
    
    # Validation
    # The oversized regex step should have been dropped. 
    # Only "remove_duplicates" should survive.
    assert len(dsl_output["transformations"]) == 1
    assert dsl_output["transformations"][0]["action"] == "remove_duplicates"
    
    # Reasoning array should now be synchronized and dropped alongside invalid steps
    assert len(dsl_output["reasoning"]) == 1

def test_parsing_recovery_handles_extra_fields():
    # Extra field 'hallucinated_field'
    raw_args = {
        "dataset_assessment": "Test dataset.",
        "hallucinated_field": "This shouldn't break the parser",
        "identified_issues": [],
        "schema_mapping_recommendations": [],
        "reasoning": [],
        "recommended_transformations": [
            {"action": "fill_missing", "column": "age", "hallucinated_step_field": "foo"}
        ]
    }
    
    mock_response = {
        "raw": AIMessage(content="", tool_calls=[{"name": "MigrationAssessment", "args": raw_args, "id": "call_1"}]),
        "parsed": None,
        "parsing_error": ValidationError.from_exception_data("title", line_errors=[])
    }
    
    provider = BaseLLMProvider(DummyLLM(mock_response))
    provider._build_prompt = MagicMock(return_value="dummy prompt")
    
    dsl_output = provider.generate_plan(profile={}, user_request=None, normalize_columns=False)
    
    assert len(dsl_output["transformations"]) == 1
    assert dsl_output["transformations"][0]["action"] == "fill_missing"
    # Ensure extra fields didn't throw an unhandled exception

def test_parsing_recovery_drops_invalid_action_types():
    raw_args = {
        "dataset_assessment": "Test dataset.",
        "identified_issues": [],
        "schema_mapping_recommendations": [],
        "reasoning": [],
        "recommended_transformations": [
            {"action": 123},  # Invalid, must be string
            {"action": "fill_missing", "column": "age"}
        ]
    }
    
    mock_response = {
        "raw": AIMessage(content="", tool_calls=[{"name": "MigrationAssessment", "args": raw_args, "id": "call_1"}]),
        "parsed": None,
        "parsing_error": ValidationError.from_exception_data("title", line_errors=[])
    }
    
    provider = BaseLLMProvider(DummyLLM(mock_response))
    provider._build_prompt = MagicMock(return_value="dummy prompt")
    
    dsl_output = provider.generate_plan(profile={}, user_request=None, normalize_columns=False)
    
    assert len(dsl_output["transformations"]) == 1
    assert dsl_output["transformations"][0]["action"] == "fill_missing"
