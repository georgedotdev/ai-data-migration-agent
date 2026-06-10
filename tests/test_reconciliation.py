import pytest
import pandas as pd
from unittest.mock import MagicMock, patch

from graph import reconciler

def test_reconciler_target_reachable_and_table_created():
    # Setup mock connectors
    source_df = pd.DataFrame({"id": [1, 2, 3]})
    target_df = pd.DataFrame({"id": [1, 2, 3]})

    state = {
        "source_type": "csv",
        "source_config": {"file_path": "dummy.csv"},
        "target_type": "duckdb",
        "target_config": {"table_name": "dummy_table"},
        "impact": {"duplicates_removed": 0},
        "executed_steps": ["migration_executor"],
        "timings": {}
    }

    with patch('graph.get_connector') as mock_get_connector:
        # First call gets source, second call gets target
        mock_source = MagicMock()
        mock_source.read_data.return_value = source_df

        mock_target = MagicMock()
        mock_target.read_data.return_value = target_df

        mock_get_connector.side_effect = [mock_source, mock_target]

        # Call reconciler
        result = reconciler(state)

        assert result["success"] is True
        assert result["reconciliation"]["rows_read"] == 3
        assert result["reconciliation"]["rows_written"] == 3
        assert result["reconciliation"]["target_reachable"] is True
        assert result["reconciliation"]["table_created"] is True
        assert result["reconciliation"]["overall_success"] is True

def test_reconciler_migration_failure():
    # Setup state where target connector throws an exception on read
    state = {
        "source_type": "csv",
        "source_config": {"file_path": "dummy.csv"},
        "target_type": "duckdb",
        "target_config": {"table_name": "dummy_table"},
        "executed_steps": ["migration_executor"],
        "timings": {}
    }

    with patch('graph.get_connector') as mock_get_connector:
        mock_source = MagicMock()
        mock_source.read_data.return_value = pd.DataFrame({"id": [1, 2]})

        mock_target = MagicMock()
        mock_target.read_data.side_effect = Exception("Target Unreachable")

        mock_get_connector.side_effect = [mock_source, mock_target]

        with patch('graph.rollback_migration') as mock_rollback:
            result = reconciler(state)
            
            assert result["success"] is False
            assert result["reconciliation"]["target_reachable"] is False
            assert result["reconciliation"]["table_created"] is False
            assert result["reconciliation"]["overall_success"] is False
            assert result["reconciliation"]["rows_written"] == 0
            
            # Ensure rollback was triggered
            mock_rollback.assert_called_once()
