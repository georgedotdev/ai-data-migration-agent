"""
Opt-in check that the real LLM connection works (costs one API call).

    RUN_LIVE_LLM=1 python -m pytest tests/test_live_llm.py -s

Skipped unless RUN_LIVE_LLM=1 and a provider key is configured (.env or environment).
"""

import os

import pandas as pd
import pytest
from dotenv import load_dotenv

load_dotenv()
KEYS = {"Gemini": "GOOGLE_API_KEY", "Groq": "GROQ_API_KEY", "OpenAI": "OPENAI_API_KEY"}
configured = [p for p, k in KEYS.items() if os.environ.get(k)]

pytestmark = pytest.mark.skipif(os.environ.get("RUN_LIVE_LLM") != "1" or not configured,
                                reason="set RUN_LIVE_LLM=1 and an API key to call a real LLM")


def test_llm_recommends_executable_transformations():
    from ai_brain import generate_transformation_dsl
    from etl.dsl_engine import execute_dsl
    from profiling.data_profiler import profile_dataframe

    df = pd.read_csv(os.path.join(os.path.dirname(__file__), "..", "data", "dirty_employees.csv"),
                     dtype=str, keep_default_na=False)
    dsl = generate_transformation_dsl(profile_dataframe(df), "Clean this HR table for migration",
                                      requested_provider=configured[0])
    meta = dsl["_metadata"]
    print(f"\nLLM used: {meta['provider_used']} / {meta['model_used']}, {len(dsl['transformations'])} steps")
    assert meta["provider_used"] in KEYS and "fallback_reason" not in dsl
    assert len(dsl["transformations"]) >= 3

    _, log, _ = execute_dsl(df, dsl)
    ok = sum(e["status"] == "success" for e in log)
    print(f"Executed {ok}/{len(log)} recommended steps successfully")
    assert ok >= 0.8 * len(log)
