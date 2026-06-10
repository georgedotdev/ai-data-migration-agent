import pandas as pd
import numpy as np
from etl.dsl_engine import execute_dsl

def test_replace_with_null():
    df = pd.DataFrame({"col": ["A", "ERROR", "UNKNOWN", "B"]})
    dsl = {
        "transformations": [
            {
                "action": "replace_with_null",
                "column": "col",
                "values": ["ERROR", "UNKNOWN"]
            }
        ]
    }
    res_df, log, quarantine = execute_dsl(df, dsl)
    
    assert log[0]["status"] == "success"
    assert res_df["col"].isna().sum() == 2
    assert list(res_df["col"].dropna()) == ["A", "B"]
