from validation.row_count import validate_row_count
from etl.validate import validate_migration


def run_all_validations(
    source_csv="data/enterprise.csv",
    db_path="migration.duckdb",
    table_name="enterprise"
):

    results = {}

    # -----------------------------
    # Row Count Validation
    # -----------------------------
    results["row_count"] = validate_row_count(
        source_csv,
        db_path,
        table_name
    )

    # -----------------------------
    # Checksum Validation
    # -----------------------------
    results["checksum"] = validate_migration(
        source_csv,
        db_path,
        table_name
    )

    # -----------------------------
    # Overall Success
    # -----------------------------
    results["overall_success"] = all(results.values())

    return results