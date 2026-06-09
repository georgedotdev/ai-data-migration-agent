import os
from dotenv import load_dotenv
load_dotenv()

from ai_brain import get_ai_provider
import pandas as pd

provider = get_ai_provider()
print(f"Provider: {type(provider).__name__}")

model_name = getattr(provider, 'model', getattr(provider, 'model_name', getattr(provider, 'llm_model', 'Unknown')))
print(f"Model: {model_name}")

if type(provider).__name__ == 'DeterministicProvider':
    print("Fallback Used: YES")
    print("GEMINI AUDIT BLOCKED: Falling back to DeterministicProvider")
    exit(1)

print("Fallback Used: NO")

try:
    df = pd.DataFrame({'a': [1]})
    provider.generate_plan(df, 'test_source', 'test_target')
    print("Gemini Connectivity: SUCCESS")
except Exception as e:
    print(f"GEMINI AUDIT BLOCKED\nError: {e}")
    exit(1)
