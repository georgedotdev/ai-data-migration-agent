"""
Tests for profiling/data_profiler.py

Covers:
- Basic profiling (flat CSV data)
- Missing value detection
- Duplicate detection
- Uniqueness and PK candidacy
- Numeric outlier detection
- Nested object detection (MongoDB-style dicts)
- Nested array detection
- Sampling behavior for large DataFrames
- Quality score computation
- Connector integration (CSVConnector)
"""

import pytest
import pandas as pd
import numpy as np

from profiling.data_profiler import (
    profile_dataframe,
    profile_data,
)


# ─────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────

@pytest.fixture
def clean_df():
    """DataFrame with no quality issues."""
    return pd.DataFrame({
        "id": [1, 2, 3, 4, 5],
        "name": ["Alice", "Bob", "Charlie", "Diana", "Eve"],
        "email": ["a@x.com", "b@x.com", "c@x.com", "d@x.com", "e@x.com"],
        "score": [90.5, 85.0, 92.3, 88.1, 95.0],
    })


@pytest.fixture
def dirty_df():
    """DataFrame with missing values, duplicates, and outliers."""
    return pd.DataFrame({
        "id": [1, 2, 3, 3, 5, 6, 7, 8, 9, 10],
        "name": ["Alice", None, "Charlie", "Charlie", None, "Frank", "Grace", None, "Ivy", "Jack"],
        "revenue": [100.0, 200.0, 150.0, 150.0, 300.0, 50.0, 9999.0, 120.0, 80.0, 110.0],
        "category": ["A", "B", "A", "A", "B", None, "C", "A", None, "B"],
    })


@pytest.fixture
def nested_df():
    """DataFrame with MongoDB-style nested objects and arrays."""
    return pd.DataFrame({
        "user_id": [1, 2, 3],
        "address": [
            {"street": "123 Main St", "city": "NYC", "zip": "10001"},
            {"street": "456 Oak Ave", "city": "LA", "zip": "90001"},
            {"street": "789 Pine Rd", "city": "CHI", "zip": "60601"},
        ],
        "tags": [
            ["premium", "active"],
            ["basic"],
            ["premium", "inactive", "flagged"],
        ],
        "name": ["Alice", "Bob", "Charlie"],
    })


# ─────────────────────────────────────────────
# Basic Profiling
# ─────────────────────────────────────────────

class TestBasicProfiling:

    def test_row_and_column_counts(self, clean_df):
        profile = profile_dataframe(clean_df)
        assert profile["row_count"] == 5
        assert profile["column_count"] == 4

    def test_all_columns_present(self, clean_df):
        profile = profile_dataframe(clean_df)
        assert set(profile["columns"].keys()) == {"id", "name", "email", "score"}

    def test_no_sampling_for_small_data(self, clean_df):
        profile = profile_dataframe(clean_df)
        assert profile["is_sampled"] is False
        assert profile["sampled_rows"] == 5

    def test_no_duplicates_in_clean_data(self, clean_df):
        profile = profile_dataframe(clean_df)
        assert profile["duplicate_rows"] == 0

    def test_quality_score_high_for_clean_data(self, clean_df):
        profile = profile_dataframe(clean_df)
        assert profile["data_quality_score"] >= 80.0


# ─────────────────────────────────────────────
# Missing Value Detection
# ─────────────────────────────────────────────

class TestMissingValues:

    def test_missing_count(self, dirty_df):
        profile = profile_dataframe(dirty_df)
        name_profile = profile["columns"]["name"]
        assert name_profile["missing_count"] == 3

    def test_missing_percentage(self, dirty_df):
        profile = profile_dataframe(dirty_df)
        name_profile = profile["columns"]["name"]
        assert name_profile["missing_pct"] == 30.0

    def test_no_missing_in_complete_column(self, dirty_df):
        profile = profile_dataframe(dirty_df)
        revenue_profile = profile["columns"]["revenue"]
        assert revenue_profile["missing_count"] == 0
        assert revenue_profile["missing_pct"] == 0.0


# ─────────────────────────────────────────────
# Duplicate Detection
# ─────────────────────────────────────────────

class TestDuplicates:

    def test_full_row_duplicates(self, dirty_df):
        profile = profile_dataframe(dirty_df)
        # Row index 3 is a duplicate of row index 2 (id=3, name=Charlie, revenue=150, cat=A)
        assert profile["duplicate_rows"] == 1

    def test_column_duplicate_count(self, dirty_df):
        profile = profile_dataframe(dirty_df)
        id_profile = profile["columns"]["id"]
        # id=3 appears twice -> 1 duplicate
        assert id_profile["duplicate_count"] == 1


# ─────────────────────────────────────────────
# Uniqueness and PK Candidacy
# ─────────────────────────────────────────────

class TestUniqueness:

    def test_unique_column_detected(self, clean_df):
        profile = profile_dataframe(clean_df)
        email_profile = profile["columns"]["email"]
        assert email_profile["unique_count"] == 5
        assert email_profile["unique_pct"] == 100.0
        assert email_profile["is_potential_pk"] is True

    def test_non_unique_column(self, dirty_df):
        profile = profile_dataframe(dirty_df)
        category_profile = profile["columns"]["category"]
        assert category_profile["is_potential_pk"] is False

    def test_column_with_nulls_not_pk(self, dirty_df):
        profile = profile_dataframe(dirty_df)
        name_profile = profile["columns"]["name"]
        # Even if unique among non-nulls, nulls disqualify PK
        assert name_profile["is_potential_pk"] is False


# ─────────────────────────────────────────────
# Numeric Outlier Detection
# ─────────────────────────────────────────────

class TestOutliers:

    def test_numeric_column_has_stats(self, dirty_df):
        profile = profile_dataframe(dirty_df)
        revenue_profile = profile["columns"]["revenue"]
        assert "numeric_stats" in revenue_profile
        stats = revenue_profile["numeric_stats"]
        assert "min" in stats
        assert "max" in stats
        assert "mean" in stats
        assert "outlier_count" in stats

    def test_outlier_detected(self, dirty_df):
        profile = profile_dataframe(dirty_df)
        stats = profile["columns"]["revenue"]["numeric_stats"]
        # 9999.0 should be flagged as an outlier
        assert stats["outlier_count"] >= 1

    def test_non_numeric_column_no_stats(self, dirty_df):
        profile = profile_dataframe(dirty_df)
        name_profile = profile["columns"]["name"]
        assert "numeric_stats" not in name_profile


# ─────────────────────────────────────────────
# Nested Structure Detection
# ─────────────────────────────────────────────

class TestNestedDetection:

    def test_nested_object_detected(self, nested_df):
        profile = profile_dataframe(nested_df)
        addr_profile = profile["columns"]["address"]
        assert addr_profile["structural_type"] == "nested_object"
        assert "street" in addr_profile["nested_keys"]
        assert "city" in addr_profile["nested_keys"]
        assert "zip" in addr_profile["nested_keys"]
        assert addr_profile["nested_depth"] == 1

    def test_nested_array_detected(self, nested_df):
        profile = profile_dataframe(nested_df)
        tags_profile = profile["columns"]["tags"]
        assert tags_profile["structural_type"] == "nested_array"

    def test_flat_column_structural_type(self, nested_df):
        profile = profile_dataframe(nested_df)
        name_profile = profile["columns"]["name"]
        assert name_profile["structural_type"] == "flat"
        assert "nested_keys" not in name_profile


# ─────────────────────────────────────────────
# Sampling Behavior
# ─────────────────────────────────────────────

class TestSampling:

    def test_large_dataset_is_sampled(self):
        large_df = pd.DataFrame({
            "id": range(20_000),
            "value": range(20_000),
        })
        profile = profile_dataframe(large_df, sample_limit=10_000)
        assert profile["is_sampled"] is True
        assert profile["sampled_rows"] == 10_000
        # row_count should still reflect the full dataset
        assert profile["row_count"] == 20_000

    def test_small_dataset_not_sampled(self):
        small_df = pd.DataFrame({
            "id": range(100),
            "value": range(100),
        })
        profile = profile_dataframe(small_df, sample_limit=10_000)
        assert profile["is_sampled"] is False
        assert profile["sampled_rows"] == 100


# ─────────────────────────────────────────────
# Quality Score
# ─────────────────────────────────────────────

class TestQualityScore:

    def test_perfect_data_high_score(self, clean_df):
        profile = profile_dataframe(clean_df)
        assert profile["data_quality_score"] >= 80.0

    def test_dirty_data_lower_score(self, dirty_df):
        profile = profile_dataframe(dirty_df)
        clean_profile = profile_dataframe(
            pd.DataFrame({
                "id": [1, 2, 3, 4, 5],
                "name": ["A", "B", "C", "D", "E"],
                "revenue": [100, 200, 150, 300, 120],
                "category": ["A", "B", "C", "A", "B"],
            })
        )
        assert profile["data_quality_score"] < clean_profile["data_quality_score"]

    def test_score_between_0_and_100(self, dirty_df):
        profile = profile_dataframe(dirty_df)
        assert 0 <= profile["data_quality_score"] <= 100

    def test_empty_dataframe_score_zero(self):
        profile = profile_dataframe(pd.DataFrame())
        assert profile["data_quality_score"] == 0.0


# ─────────────────────────────────────────────
# Sample Values
# ─────────────────────────────────────────────

class TestSampleValues:

    def test_sample_values_present(self, clean_df):
        profile = profile_dataframe(clean_df)
        assert len(profile["columns"]["name"]["sample_values"]) > 0

    def test_sample_values_capped(self):
        df = pd.DataFrame({"x": list(range(100))})
        profile = profile_dataframe(df)
        assert len(profile["columns"]["x"]["sample_values"]) <= 5

    def test_sample_values_serializable(self, clean_df):
        """All sample values must be JSON-serializable."""
        import json
        profile = profile_dataframe(clean_df)
        for col, col_profile in profile["columns"].items():
            # Should not raise
            json.dumps(col_profile["sample_values"])


# ─────────────────────────────────────────────
# Connector Integration
# ─────────────────────────────────────────────

class TestConnectorIntegration:

    def test_profile_csv_connector(self):
        """Test profiling via CSVConnector with real data."""
        import os
        csv_path = os.path.join("data", "enterprise.csv")
        if not os.path.exists(csv_path):
            pytest.skip("enterprise.csv not available")

        from connectors.csv_connector import CSVConnector
        connector = CSVConnector(csv_path)
        profile = profile_data(connector)

        assert profile["row_count"] > 0
        assert profile["column_count"] > 0
        assert profile["connector_type"] == "CSVConnector"
        assert 0 <= profile["data_quality_score"] <= 100

    def test_profile_customers_csv(self):
        """Test profiling the customers-100000.csv file."""
        import os
        csv_path = os.path.join("data", "customers-100000.csv")
        if not os.path.exists(csv_path):
            pytest.skip("customers-100000.csv not available")

        from connectors.csv_connector import CSVConnector
        connector = CSVConnector(csv_path)
        profile = profile_data(connector)

        assert profile["row_count"] == 100_000
        assert profile["column_count"] == 12
        assert profile["is_sampled"] is True
        assert profile["sampled_rows"] == 10_000
