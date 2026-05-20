from etl.extract import extract_csv
from etl.load import load_to_duckdb
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

    if step == "extract":
        df = extract_csv("data/enterprise.csv")
        print(f"Extracted {len(df)} rows.")

    elif step == "load":
        df = extract_csv("data/enterprise.csv")
        load_to_duckdb(df,"migration.duckdb","enterprise")
        print(f"Loaded data into duckdb")


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

  