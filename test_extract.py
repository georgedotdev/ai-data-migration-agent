import re
import json
import ast

error_str = '''LLM generation failed completely: Error code: 400 - {'error': {'message': "Failed to call a function. Please adjust your prompt. See 'failed_generation' for more details.", 'type': 'invalid_request_error', 'code': 'tool_use_failed', 'failed_generation': '<function=MigrationAssessment> {"dataset_assessment": "The dataset has a quality score of 84.93, indicating some data quality issues.", "identified_issues": ["nulls in hourly_rate (USD), rating, is_active, client_satisfaction", "nested objects in none", "duplicates in name, gender, primary_skill, years_of_experience, hourly_rate (USD), rating, is_active, client_satisfaction", "wrong types in hourly_rate (USD), rating"], "schema_mapping_recommendations": ["rename hourly_rate (USD) to hourly_rate", "rename rating to rating_score", "rename is_active to is_active_flag", "rename client_satisfaction to client_satisfaction_percentage"], "recommended_transformations": [{"action": "fill_missing", "column": "hourly_rate (USD)", "condition": "hourly_rate (USD) is null", "confidence": 95, "reason": "hourly_rate (USD) has 94 missing values, which is a significant portion of the data."}, {"action": "parse_currency", "column": "hourly_rate (USD)", "condition": "hourly_rate (USD) is not null", "confidence": 90, "reason": "hourly_rate (USD) contains currency values like \\'USD 100\\'."}], "reasoning": [{"step": 1, "reason": "hourly_rate (USD) has 94 missing values, which is a significant portion of the data."}, {"step": 2, "reason": "hourly_rate (USD) contains currency values like \\'USD 100\\'."}]}'}}'''

def extract_failed_generation(error_msg):
    # Try finding the 'failed_generation' substring directly
    idx = error_msg.find("'failed_generation':")
    if idx != -1:
        start_quote = error_msg.find("'", idx + 20)
        if start_quote != -1:
            end_quote = error_msg.find("'}", start_quote)
            if end_quote != -1:
                failed_gen = error_msg[start_quote+1:end_quote]
                print("Extracted failed_gen:", failed_gen)
                start_idx = failed_gen.find('{')
                if start_idx != -1:
                    raw_content = failed_gen[start_idx:]
                    raw_content = raw_content.replace("\\'", "'")
                    try:
                        return json.loads(raw_content)
                    except json.JSONDecodeError as e:
                        print("JSON Error:", e)
                        print("Raw to parse:", raw_content)
    return None

parsed = extract_failed_generation(error_str)
print("Parsed dict keys:", parsed.keys() if parsed else None)
