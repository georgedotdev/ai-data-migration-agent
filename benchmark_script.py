import os
import sys
import uuid
import json
import traceback

from graph import graph

def run_benchmark(custom_files=None):
    os.makedirs('benchmark/runs', exist_ok=True)
    
    if custom_files:
        datasets = custom_files
    else:
        datasets = [
            'customer_data.csv',
            'fitness_dataset.csv',
            'messy_clinic_appointments.csv',
            'Messy_Employee_dataset.csv',
            'messy_IMDB_dataset.csv'
        ]
    
    for filename in datasets:
        print(f"\n--- Running benchmark on {filename} ---")
        dataset_name = filename.split('.')[0]
        report_file = f"benchmark/runs/{dataset_name}_groq_report.json"
        
        # Initial State
        initial_state = {
            "query": f"Migrate and clean data from {filename}",
            "ai_provider": "Groq",
            "ai_model": "llama-3.3-70b-versatile",
            "source_type": "csv",
            "target_type": "duckdb",
            "source_config": {"file_path": f"csv_files/{filename}"},
            "target_config": {"db_path": f"benchmark/runs/{dataset_name}.duckdb", "table_name": dataset_name},
            "table_name": dataset_name,
            "plan_approved": False,
            "executed_steps": [],
            "timings": {}
        }
        
        thread_id = str(uuid.uuid4())
        config = {"configurable": {"thread_id": thread_id}}
        
        result_data = {
            "dataset": filename,
            "success": False,
            "error": None,
            "raw_prompt": None,
            "raw_response": None,
            "parsed_dsl": None,
            "execution_log": None,
            "impact_summary": None,
            "executive_report": None
        }
        
        try:
            # Run to human review
            print("Running to human review...")
            state_iter = graph.invoke(initial_state, config=config)
            current_state = graph.get_state(config).values
            
            result_data["raw_prompt"] = current_state.get("raw_prompt")
            result_data["raw_response"] = current_state.get("raw_ai_response")
            result_data["parsed_dsl"] = current_state.get("transformation_dsl")
            result_data["impact_summary"] = current_state.get("preview_impact")
            
            # Approve and continue
            print("Approving and executing...")
            resume_state = {
                "plan_approved": True,
                "human_feedback": ""
            }
            graph.update_state(config, resume_state)
            final_state = graph.invoke(None, config=config)
            
            result_data["execution_log"] = final_state.get("execution_log")
            result_data["executive_report"] = final_state.get("report")
            result_data["success"] = final_state.get("success", False)
            
        except Exception as e:
            err_msg = str(e) + "\n" + traceback.format_exc()
            print(f"Failed: {e}")
            result_data["error"] = err_msg
            
        with open(report_file, 'w', encoding='utf-8') as f:
            json.dump(result_data, f, indent=2)
            
        print(f"Saved report to {report_file}")

if __name__ == "__main__":
    import sys
    run_benchmark(sys.argv[1:] if len(sys.argv) > 1 else None)
