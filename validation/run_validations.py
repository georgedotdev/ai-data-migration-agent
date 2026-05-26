from validation.row_count import validate_row_count
from etl.validate import validate_migration


def run_all_validations():

    results = {}

    # -----------------------------
    # Row Count Validation
    # -----------------------------
    results["row_count"] = validate_row_count(
        "data/enterprise.csv",
        "migration.duckdb",
        "enterprise"
    )

    # -----------------------------
    # Checksum Validation
    # -----------------------------
    results["checksum"] = validate_migration(
        "data/enterprise.csv",
        "migration.duckdb",
        "enterprise"
    )

    # -----------------------------
    # Overall Success
    # -----------------------------
    results["overall_success"] = all(results.values())

    return results