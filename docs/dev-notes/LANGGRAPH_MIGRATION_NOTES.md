# LangGraph Migration Agent Notes

## What This Project Is Trying To Become

The current project migrates data from a CSV file into DuckDB, then checks whether the migration worked by comparing row counts and checksums.

The future version can use LangGraph to turn this into a proper agent workflow. Instead of one script doing everything directly, the migration is broken into clear stages:

1. Understand the source database
2. Understand the target database
3. Compare schemas
4. Create a migration plan
5. Execute the migration
6. Validate the result
7. Roll back or repair if something fails
8. Generate a final report

LangGraph is useful because each stage can become a node in a graph. The graph controls what happens next based on the current migration state.

## Simple Way To Explain LangGraph

LangGraph lets you build workflows made of nodes and edges.

- A node is a function that does one job.
- An edge decides which node runs next.
- The state is shared information passed through the workflow.

For this project, the shared state could contain things like:

```python
{
    "source_type": "postgres",
    "target_type": "snowflake",
    "source_connection": "...",
    "target_connection": "...",
    "tables": [],
    "schemas": {},
    "migration_plan": [],
    "validation_results": {},
    "errors": [],
    "success": False
}
```

The graph keeps updating this state as the migration progresses.

## Why LangGraph Helps Here

Normal scripts usually run in a straight line:

```text
read source -> write target -> validate -> finish
```

But real database migration is not always linear. For example:

- If schema discovery fails, the agent should stop and ask for better credentials.
- If the target table does not exist, the agent should create it.
- If validation fails, the agent should retry, repair, or roll back.
- If one table succeeds and another fails, the agent should continue safely or pause.

LangGraph is good for this because it supports conditional paths:

```text
plan migration
    -> discover source schema
    -> discover target schema
    -> compare schemas
    -> execute migration
    -> validate
        -> success: generate report
        -> failure: rollback or repair
```

## Future Architecture

The future version should be built around database adapters and LangGraph nodes.

## 1. Database Adapters

To support "any database to any database", the project should not write direct PostgreSQL, DuckDB, MySQL, or Snowflake logic everywhere.

Instead, create a common adapter interface.

Example:

```python
class DatabaseAdapter:
    def connect(self):
        pass

    def list_tables(self):
        pass

    def get_schema(self, table_name):
        pass

    def read_table(self, table_name):
        pass

    def create_table(self, table_name, schema):
        pass

    def write_table(self, table_name, dataframe):
        pass

    def count_rows(self, table_name):
        pass

    def checksum_table(self, table_name):
        pass

    def rollback_table(self, table_name):
        pass
```

Then implement specific adapters:

```text
DuckDBAdapter
PostgresAdapter
MySQLAdapter
SQLServerAdapter
SnowflakeAdapter
BigQueryAdapter
```

The LangGraph workflow does not need to care which database is being used. It only talks to the adapter.

That is the key design idea.

## 2. LangGraph State

The graph needs one shared state object.

Example:

```python
from typing import TypedDict, Any

class MigrationState(TypedDict):
    source_type: str
    target_type: str
    source_config: dict
    target_config: dict
    source_adapter: Any
    target_adapter: Any
    tables: list[str]
    schemas: dict
    migration_plan: list[dict]
    current_table: str | None
    validation_results: dict
    errors: list[str]
    success: bool
```

This is the memory of the migration run.

## 3. LangGraph Nodes

Each major step becomes a function.

### Planner Node

Decides what needs to happen.

Example responsibilities:

- identify source and target database types
- decide which tables to migrate
- decide migration order
- detect whether full load or incremental load is needed

### Source Discovery Node

Connects to the source database and discovers:

- tables
- columns
- datatypes
- primary keys
- nullable fields
- row counts

### Target Discovery Node

Checks what already exists in the target database.

It answers:

- does the target table already exist?
- does the schema match?
- should the table be created, replaced, or altered?

### Schema Mapping Node

Maps source datatypes to target datatypes.

Example:

```text
PostgreSQL INTEGER -> Snowflake NUMBER
MySQL VARCHAR -> BigQuery STRING
DuckDB DOUBLE -> PostgreSQL DOUBLE PRECISION
```

This is one of the most important parts if the project needs to support many databases.

### Migration Execution Node

Actually moves the data.

For the prototype, this can still use Pandas:

```text
read table into dataframe -> write dataframe to target
```

Later, for larger migrations, this should use chunking:

```text
read 10,000 rows -> write 10,000 rows -> repeat
```

For production-scale systems, it may use database-native exports, bulk loaders, or cloud storage staging.

### Validation Node

Checks whether the migration succeeded.

Validation can include:

- source row count equals target row count
- source checksum equals target checksum
- null counts match
- key columns are unique
- sample records match
- business rules pass

### Rollback Node

Runs if validation fails.

Rollback can:

- drop created tables
- delete inserted rows
- restore from backup
- mark the migration as failed

### Report Node

Creates a final migration report:

```text
Migration status: Success
Source: PostgreSQL
Target: DuckDB
Tables migrated: 5
Rows migrated: 120,000
Validation: Passed
Rollback required: No
```

## 4. Conditional Routing

The biggest benefit of LangGraph is conditional routing.

Example:

```text
validate migration
    if success -> report
    if failure -> rollback
```

In code, this usually means writing a router function:

```python
def validation_router(state):
    if state["success"]:
        return "report"
    return "rollback"
```

That router decides the next graph node.

## Example Graph Shape

```text
START
  |
  v
planner
  |
  v
connect_source
  |
  v
connect_target
  |
  v
discover_source_schema
  |
  v
discover_target_schema
  |
  v
map_schema
  |
  v
execute_migration
  |
  v
validate_migration
  |
  +---- success ----> generate_report ----> END
  |
  +---- failure ----> rollback -----------> generate_report ----> END
```

## How This Fits The Current Project

Your current functions already match some future LangGraph nodes.

Current function:

```python
discover_schema(csv_file)
```

Future LangGraph node:

```text
discover_source_schema
```

Current function:

```python
migrate_csv_to_duckdb(csv_file, table_name)
```

Future LangGraph node:

```text
execute_migration
```

Current function:

```python
dataframe_checksum(df)
```

Future LangGraph node:

```text
validate_migration
```

Current function:

```python
rollback(table_name)
```

Future LangGraph node:

```text
rollback
```

So the current project is not wasted. It is the base logic that can be wrapped inside LangGraph nodes.

## How To Explain The Final Vision

You can describe it like this:

> The project starts as a CSV-to-DuckDB migration prototype. The next step is to convert the linear migration script into a LangGraph workflow. Each stage of the migration becomes a graph node: planning, schema discovery, schema mapping, data transfer, validation, rollback, and reporting. To support any database-to-database migration, the system will use database adapters. Each adapter hides the database-specific details, while LangGraph controls the overall migration process and decides what to do when a step succeeds or fails.

## Practical Implementation Roadmap

### Phase 1: Clean The Current Prototype

- Remove notebook-only code from `graph.py`
- Move reusable logic into separate modules
- Add a small sample CSV
- Make the existing CSV-to-DuckDB path run cleanly

Suggested structure:

```text
src/
  adapters/
    duckdb_adapter.py
    csv_adapter.py
  migration/
    checksum.py
    validation.py
    rollback.py
  graph/
    state.py
    nodes.py
    workflow.py
```

### Phase 2: Add LangGraph

- Define `MigrationState`
- Convert each function into a LangGraph node
- Add conditional routing after validation
- Compile and run the graph

### Phase 3: Add More Databases

- Add PostgreSQL adapter
- Add MySQL adapter
- Add SQL Server adapter
- Add Snowflake or BigQuery adapter

Each adapter should follow the same interface.

### Phase 4: Improve Validation

- Add row count validation
- Add checksum validation
- Add null-count validation
- Add schema compatibility validation
- Add sample-record validation

### Phase 5: Make It Production-Like

- Add logging
- Add config files
- Add chunked migration
- Add retry handling
- Add generated reports
- Add tests

## Main Point To Remember

LangGraph should not be the part that knows how every database works.

The database adapters know how each database works.

LangGraph knows the migration process:

```text
plan -> discover -> map -> migrate -> validate -> rollback/report
```

That separation is what will make the project expandable from CSV-to-DuckDB into any-database-to-any-database migration.
