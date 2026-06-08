"""
Validation Runner

Connector-generic validation orchestrator.
Accepts connector instances instead of file paths.
"""

from validation.row_count import validate_row_count
from etl.validate import validate_migration
from connectors.csv_connector import CSVConnector
from connectors.duckdb_connector import DuckDBConnector


def run_all_validations(
    source_connector=None,
    target_connector=None,
    validations=None,
    transformations=None,
    dsl_transformations=None
):
    """
    Run selected validations against source and target connectors.

    If validations is None, run all (backward compatible).
    If validations is a list, run only the specified ones.

    Transformations and dsl_transformations are passed through
    so validators apply the same transforms used during migration.

    When checksum fails, diagnostics are run automatically.
    """

    # Backward compatibility for older scripts/tests that called
    # run_all_validations() with no connector instances.
    if source_connector is None:
        source_connector = CSVConnector("data/enterprise.csv")
    if target_connector is None:
        target_connector = DuckDBConnector("migration.duckdb", "enterprise")

    # Default: run all validations
    if validations is None:
        validations = ["row_count", "checksum"]

    results = {}

    # -----------------------------
    # Row Count Validation
    # -----------------------------
    if "row_count" in validations:
        results["row_count"] = validate_row_count(
            source_connector,
            target_connector,
            transformations=transformations,
            dsl_transformations=dsl_transformations
        )

    # -----------------------------
    # Checksum Validation
    # -----------------------------
    if "checksum" in validations:
        results["checksum"] = validate_migration(
            source_connector,
            target_connector,
            transformations=transformations,
            dsl_transformations=dsl_transformations
        )

    # -----------------------------
    # Overall Success
    # -----------------------------
    results["overall_success"] = (
        all(results.values()) if results else True
    )

    # -----------------------------
    # Diagnostics on Failure
    # -----------------------------
    if not results.get("checksum", True) or not results.get("row_count", True):
        from validation.diagnostics import run_diagnostics
        results["diagnostics"] = run_diagnostics(
            source_connector,
            target_connector,
            transformations=transformations,
            dsl_transformations=dsl_transformations
        )
    else:
        results["diagnostics"] = None

    return results
