import re
import os

def audit_coverage():
    # 1. Read prompted actions from ai_brain.py
    ai_brain_path = "ai_brain.py"
    prompted_actions = set()
    with open(ai_brain_path, "r", encoding="utf-8") as f:
        content = f.read()
        match = re.search(r'Available DSL Actions include:(.*?)For each DSL Action', content, re.DOTALL)
        if match:
            lines = match.group(1).strip().split('\n')
            for line in lines:
                if ':' in line:
                    actions_part = line.split(':', 1)[1]
                    # Extract words that look like actions (e.g., lowercase with underscores)
                    actions = re.findall(r'[a-z_]+', actions_part)
                    prompted_actions.update([a for a in actions if len(a) > 2 and a not in ('mean', 'median', 'mode', 'constant', 'forward_fill', 'backward_fill', 'int', 'float', 'str', 'datetime', 'bool', 'e', 'g')])

    # Add implicitly prompted actions or ones from the main schema
    prompted_actions.add('normalize_columns')

    # 2. Search for implemented handlers
    implemented_handlers = {}
    
    def scan_file(filepath):
        if not os.path.exists(filepath): return
        with open(filepath, "r", encoding="utf-8") as f:
            for line_no, line in enumerate(f, 1):
                match = re.search(r'def _action_([a-z_]+)\(', line)
                if match:
                    action_name = match.group(1)
                    implemented_handlers[action_name] = (os.path.basename(filepath), line_no)

    scan_file(os.path.join("etl", "dsl_engine.py"))
    scan_file(os.path.join("etl", "dsl_handlers_extended.py"))

    # 3. Generate Report
    print("=== Transformation Coverage Report ===")
    
    implemented_count = 0
    missing_count = 0
    
    for action in sorted(prompted_actions):
        if action in implemented_handlers:
            file, line = implemented_handlers[action]
            print(f"{action} -> IMPLEMENTED (File: {file}, Line: {line})")
            implemented_count += 1
        else:
            print(f"{action} -> MISSING")
            missing_count += 1
            
    print("\n=== Summary ===")
    print(f"AI_RECOMMENDED_ACTIONS: {len(prompted_actions)}")
    print(f"IMPLEMENTED_ACTIONS: {implemented_count}")
    print(f"MISSING_ACTIONS: {missing_count}")
    
    if len(prompted_actions) > 0:
        coverage = (implemented_count / len(prompted_actions)) * 100
        print(f"\nTransformation Coverage %: {coverage:.2f}%")

if __name__ == "__main__":
    audit_coverage()
