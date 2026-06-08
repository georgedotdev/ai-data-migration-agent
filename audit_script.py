import json
from migration_service import generate_ai_plan

result = generate_ai_plan(
    user_request="Migrate data",
    source_type="csv",
    source_config={"file_path": "data/enterprise.csv"}
)

print(json.dumps(result["plan"], indent=2, default=str))
