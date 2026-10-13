import pandas as pd
import pytest

from connectors.postgres_connector import PostgreSQLConnector


@pytest.mark.parametrize("bad", ["My Test-Table", 'x"; DROP TABLE users; --', "1abc"])
def test_postgres_connector_rejects_unsafe_identifiers(bad):
    """Table names are interpolated into SQL, so anything but [A-Za-z0-9_] is refused before any query runs."""
    c = PostgreSQLConnector(host="127.0.0.1", table_name=bad)
    with pytest.raises(ValueError):
        c.write_data(pd.DataFrame({"a": [1]}))
    with pytest.raises(ValueError):
        c.read_data()
    with pytest.raises(ValueError):
        c.count_rows()
