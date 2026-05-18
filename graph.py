# -*- coding: utf-8 -*-
"""

import pandas as pd
import duckdb
import hashlib


def dataframe_checksum(df):
  df = df.reindex(sorted(df.columns), axis = 1)

  df = df.astype(str)

  df = df.sort_values(by=list(df.columns)).reset_index(drop=True)

  data_string = df.to_csv(index=False)

  return hashlib.sha256(data_string.encode()).hexdigest()


# Read source
source_df = pd.read_csv("enterprise.csv")

# Read target
target_df = con.execute("SELECT * FROM customers").fetchdf()

# Compute checksums
source_checksum = dataframe_checksum(source_df)
target_checksum = dataframe_checksum(target_df)

print("Source Checksum:", source_checksum)
print("Target Checksum:", target_checksum)

if source_checksum == target_checksum:
    print("✅ Checksums match.")
else:
    print("❌ Checksums do not match.")


#Sample migration function


def migrate_csv_to_duckdb(csv_file, table_name, db_file="migration.duckdb"):
    import pandas as pd
    import duckdb

    # Read source CSV
    df = pd.read_csv(csv_file)

    # Connect to DuckDB
    con = duckdb.connect(db_file)

    # Replace table
    con.execute(f"DROP TABLE IF EXISTS {table_name}")
    con.execute(f"CREATE TABLE {table_name} AS SELECT * FROM df")

    # Validate row counts
    source_count = len(df)
    target_count = con.execute(
        f"SELECT COUNT(*) FROM {table_name}"
    ).fetchone()[0]

    print(f"Source Count: {source_count}")
    print(f"Target Count: {target_count}")

    if source_count == target_count:
        print("✅ Migration successful")
    else:
        print("❌ Migration failed")

    con.close()

migrate_csv_to_duckdb(
    "enterprise.csv",
    "enterprise"
)

def rollback(table_name, db_file="migration.duckdb"):
    import duckdb

    con = duckdb.connect(db_file)
    con.execute(f"DROP TABLE IF EXISTS {table_name}")
    con.close()

    print(f"Rolled back: {table_name}")



import pandas as pd
import hashlib
import duckdb
from typing import TypedDict
from typing import Annotated
from operator import add
from typing_extensions import TypedDict
from etl.validate import validate_migration
class AgentState(TypedDict):
  query : str
  plan : list[str]
  executed_steps : Annotated[list[str], add]
  context : str
  success : bool

def planner(state: AgentState):
  return {
      "plan" : ["extract","transform","load"]
  }

def retriever(state: AgentState):
  return {
      "context": "source and target schema"
  }

def executor(state: AgentState):
  if state["plan"]:
    step = state["plan"][0]

    remaining_steps = state["plan"][1:]

  return {}

def tester(state: AgentState):
    is_valid = validate_migration("data/enterprise.csv","migration.duckdb","enterprise")


    return {"success" : is_valid}


def supervisor(state: AgentState):
    # Final review / reporting can be added here later
    return {}
def dataframe_checksum(df):
  df = df.reindex(sorted(df.columns), axis = 1)

  df = df.astype(str)

  df = df.sort_values(by=list(df.columns)).reset_index(drop=True)

  data_string = df.to_csv(index=False)

  return hashlib.sha256(data_string.encode()).hexdigest()


def rollback(table_name, db_file="migration.duckdb"):
  con = duckdb.connect(db_file)
  con.execute(f"DROP TABLE IF EXISTS {table_name}")
  con.close()

  print(f"Rolled back: {table_name}")


def migrate_csv_to_duckdb(csv_file, table_name, db_file="migration.duckdb"):
  #source file
  source_df = pd.read_csv(csv_file)

  #target file
  con = duckdb.connect(db_file)

  con.execute(f"DROP TABLE IF EXISTS {table_name}")
  con.execute(f"CREATE TABLE {table_name} AS SELECT * FROM source_df")


  source_count = len(source_df)
  target_count = con.execute(f"SELECT COUNT(*) FROM {table_name}").fetchone()[0]

  target_df = con.execute(f"SELECT * FROM {table_name}").fetchdf()

  target_checksum = dataframe_checksum(target_df)
  source_checksum = dataframe_checksum(source_df)



  counts_check = source_count == target_count
  checksum_check = source_checksum == target_checksum

  if counts_check == False or checksum_check == False:
    rollback(table_name)

  con.close()
  return {
      "status":"Success" if counts_check and checksum_check else "Failed",
      "counts_check":counts_check,
      "checksum_check":checksum_check,
      "source_rows" : source_count,
      "target_rows" : target_count,
      "source_checksum" : source_checksum,
      "target_checksum" : target_checksum
  }


def discover_schema(csv_file):
  df = pd.read_csv(csv_file)

  schema_dict = {}
  null_values = df.isnull().sum()
  unique_counts = df.nunique()

  for col in df.columns:
    schema_dict[col] = {
        "dtype": str(df[col].dtype),
        "nulls": int(null_values[col]),
        "unique": int(unique_counts[col])
    }
  print(schema_dict)

def plan_migration(csv_file,table_name):
  return [
      "Discover schema",
        "Migrate data",
        "Validate results",
        "Rollback if validation fails",
        "Generate report"
  ]

def run_agent(csv_file,table_name):
  plan_migration = plan_migration(csv_file,table_name)
  for step in plan_migration:
    if step == "Discover schema":
      discover_schema(csv_file)
discover_schema("/content/sample_data/california_housing_test.csv")

#report = migrate_csv_to_duckdb(
   # "/content/sample_data/mnist_train_small.csv",
   # "train_small"
#)
#print(report)


"""

from typing import TypedDict
from langgraph.graph import StateGraph, END
from etl.validate import validate_migration

class AgentState(TypedDict):
    query: str
    plan: list[str]
    executed_steps: list[str]
    context: str
    success: bool

def planner(state: AgentState):
    return {
        "plan": ["extract", "load"]
    }

def retriever(state: AgentState):
    return {
        "context":"CSV to duckdb migration"
    }

def executor(state: AgentState):
    if not state["plan"]:
        return {}
    

    step = state["plan"][0]

    return {
        "plan" : state["plan"][1:],
        "executed_steps": state["executed_steps"] + [step]
    }

def should_continue(state: AgentState):
    if state["plan"]:
        return "executor"
    return "tester"

def tester(state: AgentState):
    is_valid = validate_migration(
        "data/enterprise.csv",
        "migration.duckdb",
        "enterprise"
    )

    return {
        "success": is_valid
    }
def supervisor(state: AgentState):
    return {}

builder = StateGraph(AgentState)

builder.add_node("planner", planner)
builder.add_node("retriever", retriever)
builder.add_node("executor", executor)
builder.add_node("tester", tester)
builder.add_node("supervisor", supervisor)

builder.set_entry_point("planner")

builder.add_edge("planner", "retriever")
builder.add_edge("retriever", "executor")

builder.add_conditional_edges(
    "executor",
    should_continue,
    {
        "executor": "executor",
        "tester": "tester"
    }
)
builder.add_edge("tester", "supervisor")
builder.add_edge("supervisor", END)

graph = builder.compile()


if __name__ == "__main__":
    initial_state = {
        "query": "Migrate enterprise data",
        "plan": [],
        "executed_steps": [],
        "context": "",
        "success": False
    }

    result = graph.invoke(initial_state)
    print(result)

  