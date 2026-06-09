import pandas as pd
import numpy as np
import json
from etl.preview import generate_impact_summary
from etl.dsl_engine import execute_dsl

# Create dataset with exactly 100 missing values
data = {'id': range(1, 201), 'score': [100.0] * 100 + [np.nan] * 100}
df_before = pd.DataFrame(data)

# Force a transformation that fills missing values and a bad cast that might coerce
dsl = {
    "transformations": [
        {"action": "fill_missing", "column": "score", "strategy": "constant", "value": 0.0},
        {"action": "cast_type", "column": "score", "target_type": "int64"}
    ]
}

# Run execution
df_after, log = execute_dsl(df_before, dsl)

# Run impact summary
impact = generate_impact_summary(df_before, df_after, dsl)

print(json.dumps(impact, indent=2))
