import duckdb

conn = duckdb.connect("enterprise.duckdb")

print(conn.execute("SHOW TABLES").fetchall())

df = conn.execute("SELECT * FROM enterprise LIMIT 10").df()

print(df)

conn.close()