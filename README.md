# AI Data Migration Agent

## Overview

AI Data Migration Agent is an agentic data migration framework built using LangGraph. The system orchestrates schema discovery, extraction, transformation, loading, validation, and reporting through a state-driven workflow designed to support future migration scenarios across multiple data platforms.

The project demonstrates how agentic workflows can be applied to data migration by combining orchestration, connector abstractions, validation pipelines, retry mechanisms, rollback handling, and operational dashboards into a unified framework.

Current supported migration path:

```text
CSV → DuckDB
```

The architecture is designed to support additional source and target systems such as PostgreSQL, MongoDB, Snowflake, BigQuery, and other enterprise data platforms through a connector-based approach.

---

## Features

### Agentic Workflow Orchestration

Built using LangGraph with a state-driven workflow:

```text
Planner
↓
Retriever
↓
Executor
↓
Tester
↓
Supervisor
```

The workflow manages migration execution through a shared AgentState object.

---

### Schema Discovery

Automatically analyzes source datasets and extracts:

* Column names
* Data types
* Nullability
* Uniqueness information
* Primary key candidate inference
* Row count
* Column count

---

### Data Migration Pipeline

Supports:

* Data extraction
* Data transformation
* Data loading
* Validation
* Reporting

Current migration path:

```text
CSV → DuckDB
```

---

### Transformation Engine

Performs:

* Column normalization
* Data type conversions
* Null handling
* Schema standardization

Example transformations:

* Convert column names to lowercase
* Handle missing values
* Normalize data types

---

### Validation Framework

Ensures migration integrity through:

#### Row Count Validation

Verifies:

```text
Source Rows == Target Rows
```

#### Checksum Validation

Computes deterministic SHA-256 checksums across source and target datasets to verify data consistency.

---

### Reliability Features

#### Retry Logic

Automatic retry handling for migration failures.

Features:

* Multiple retry attempts
* Failure logging
* Recovery from transient errors

#### Rollback Support

If validation fails:

```text
Migration
↓
Validation Failure
↓
Rollback
```

The target environment is restored to a clean state.

---

### Connector Abstraction Layer

Migration logic is decoupled from specific data systems.

Current connectors:

```text
CSVConnector
DuckDBConnector
```

Architecture:

```text
Source Connector
↓
Transformation Layer
↓
Target Connector
```

This design allows new database systems to be added without modifying orchestration logic.

---

### Streamlit Operations Dashboard

Provides:

* Migration configuration
* Pipeline execution status
* Schema discovery visualization
* Validation results
* Timing metrics
* Data previews
* Historical migration reports
* Benchmark execution

---

### Benchmark Runner

Supports:

* Multi-dataset testing
* SLA verification
* Timing analysis
* Validation benchmarking
* CSV/JSON export

---

## Project Structure

```text
ai-data-migration-agent/
│
├── app.py
├── graph.py
├── migration_service.py
├── requirements.txt
│
├── connectors/
│   ├── base_connector.py
│   ├── csv_connector.py
│   └── duckdb_connector.py
│
├── etl/
│   ├── extract.py
│   ├── transform.py
│   ├── load.py
│   ├── schema.py
│   ├── validate.py
│   └── rollback.py
│
├── validation/
│   ├── row_count.py
│   └── run_validations.py
│
├── pages/
│   └── Benchmark_Runner.py
│
├── reports/
│
├── data/
│   └── enterprise.csv
│
└── migration.duckdb
```

---

## Technology Stack

### Orchestration

* LangGraph

### Data Processing

* Pandas

### Database

* DuckDB

### Validation

* SHA-256 Checksum Validation

### Dashboard

* Streamlit

### Language

* Python

---

## Running the Project

### Clone Repository

```bash
git clone <repository-url>
cd ai-data-migration-agent
```

### Create Virtual Environment

```bash
python -m venv venv
```

### Activate Environment

Windows:

```bash
venv\Scripts\activate
```

### Install Dependencies

```bash
pip install -r requirements.txt
```

---

## Run LangGraph Workflow

```bash
python graph.py
```

---

## Run Dashboard

```bash
python -m streamlit run app.py
```

---

## Example Workflow

```text
Upload CSV
↓
Schema Discovery
↓
Extract
↓
Transform
↓
Load
↓
Validate
↓
Generate Report
```

---

## Current Capabilities

✅ CSV to DuckDB migration

✅ Schema discovery

✅ Transformation engine

✅ Validation framework

✅ Retry logic

✅ Rollback handling

✅ Connector abstraction

✅ Streamlit dashboard

✅ Benchmark runner

✅ Migration reporting

---

## Future Roadmap

### Additional Connectors

Planned support for:

* PostgreSQL
* MongoDB
* Snowflake
* BigQuery
* Parquet

### Enhanced Validation

* Schema parity validation
* Nullability validation
* Uniqueness validation

### Enterprise Features

* Batch processing
* Chunked migrations
* Large dataset optimization
* Advanced observability
* Automated SLA monitoring

---

