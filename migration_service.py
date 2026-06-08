"""
Migration Service Layer (V2)

Provides helper functions for the Streamlit UI to interact with
the LangGraph V2 agentic workflow.
"""

from graph import graph

def start_migration(thread_id: str, initial_state: dict):
    """
    Start the LangGraph workflow up to the human review breakpoint.
    """
    config = {"configurable": {"thread_id": thread_id}}
    return graph.invoke(initial_state, config=config)


def get_agent_state(thread_id: str):
    """
    Retrieve the current state snapshot from the MemorySaver checkpointer.
    """
    config = {"configurable": {"thread_id": thread_id}}
    return graph.get_state(config)


def resume_migration(thread_id: str, plan_approved: bool, human_feedback: str = ""):
    """
    Resume the LangGraph workflow with human feedback.
    """
    config = {"configurable": {"thread_id": thread_id}}
    resume_state = {
        "plan_approved": plan_approved,
        "human_feedback": human_feedback
    }
    graph.update_state(config, resume_state)
    return graph.invoke(None, config=config)


# Backward compatibility wrappers for older scripts that may still
# import generate_ai_plan or run_full_migration.
import uuid

def generate_ai_plan(*args, **kwargs):
    raise NotImplementedError("generate_ai_plan is deprecated in V2. Use start_migration instead.")

def run_full_migration(*args, **kwargs):
    raise NotImplementedError("run_full_migration is deprecated in V2. Use graph.run_migration instead.")
