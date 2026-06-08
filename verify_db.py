from sqlalchemy import create_engine, text

engine = create_engine('postgresql+psycopg2://migration:migration123@127.0.0.1:5432/migration_db')

with engine.connect() as conn:
    result = conn.execute(text("SELECT table_name FROM information_schema.tables WHERE table_schema='public'"))
    tables = [r[0] for r in result.fetchall()]
    print('Found tables:', tables)
    for t in tables:
        try:
            count = conn.execute(text(f'SELECT COUNT(*) FROM "{t}"')).scalar()
            print(f'Table "{t}": {count} rows')
        except Exception as e:
            print(f'Table "{t}": Error querying count -> {e}')
