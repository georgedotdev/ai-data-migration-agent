"""
Validation Runner

Connector-generic validation orchestrator.
Accepts connector instances instead of file paths.
"""

from validation.row_count import validate_row_count
from etl.validate import validate_migration


def run_all_validations(
    source_connector,
    target_connector,
    validations=None,
    transformations=None
):
    """
    Run selected validations against source and target connectors.

    If validations is None, run all (backward compatible).
    If validations is a list, run only the specified ones.

    Transformations is passed through to checksum validation
    so it applies the same transforms used during migration.

    When checksum fails, diagnostics are run automatically.
    """

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
            target_connector
        )

    # -----------------------------
    # Checksum Validation
    # -----------------------------
    if "checksum" in validations:
        results["checksum"] = validate_migration(
            source_connector,
            target_connector,
            transformations=transformations
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
    if not results.get("checksum", True):
        from validation.diagnostics import run_diagnostics
        results["diagnostics"] = run_diagnostics(
            source_connector,
            target_connector,
            transformations=transformations
        )
    else:
        results["diagnostics"] = None

    return results