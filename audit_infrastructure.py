import subprocess
import psycopg2
from pymongo import MongoClient
import traceback

def verify_docker():
    print("--- DOCKER VERIFICATION ---")
    try:
        result = subprocess.run(["docker", "ps"], capture_output=True, text=True, check=True)
        print("Docker is running. Containers:")
        print(result.stdout)
    except Exception as e:
        print(f"Docker verification failed: {e}")

def verify_postgres():
    print("\n--- POSTGRES VERIFICATION ---")
    try:
        conn = psycopg2.connect(
            host="127.0.0.1", port=5432, user="migration", password="migration123", dbname="migration_db"
        )
        cur = conn.cursor()
        cur.execute("SELECT version();")
        print(f"Version: {cur.fetchone()[0]}")
        
        cur.execute("SELECT current_database();")
        print(f"Current DB: {cur.fetchone()[0]}")
        
        cur.execute("SELECT current_user;")
        print(f"Current User: {cur.fetchone()[0]}")
        
        cur.execute("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = 'public'
        """)
        tables = cur.fetchall()
        print("\nTables in public schema:")
        for table in tables:
            t_name = table[0]
            cur.execute(f'SELECT COUNT(*) FROM "{t_name}"')
            count = cur.fetchone()[0]
            print(f"- {t_name}: {count} rows")
            
        # Test create/insert/read/drop
        cur.execute("CREATE TABLE audit_postgres_test (id INT, val VARCHAR);")
        cur.execute("INSERT INTO audit_postgres_test VALUES (1, 'A'), (2, 'B'), (3, 'C'), (4, 'D'), (5, 'E');")
        cur.execute("SELECT COUNT(*) FROM audit_postgres_test;")
        print(f"audit_postgres_test count: {cur.fetchone()[0]}")
        cur.execute("DROP TABLE audit_postgres_test;")
        conn.commit()
        print("Postgres Insert/Read/Drop successful.")
        
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Postgres verification failed: {e}")

def verify_mongodb():
    print("\n--- MONGODB VERIFICATION ---")
    try:
        client = MongoClient("mongodb://localhost:27017", serverSelectionTimeoutMS=2000)
        client.admin.command('ping')
        print("MongoDB Ping: Success")
        
        db = client["migration_db"]
        collections = db.list_collection_names()
        print("Collections in migration_db:")
        for c in collections:
            count = db[c].count_documents({})
            print(f"- {c}: {count} documents")
            
        # Test create/insert/read/drop
        test_coll = db["audit_mongo_test"]
        test_coll.insert_many([{"id": i, "val": "test"} for i in range(5)])
        print(f"audit_mongo_test count: {test_coll.count_documents({})}")
        test_coll.drop()
        print("MongoDB Insert/Read/Drop successful.")
        
    except Exception as e:
        print(f"MongoDB verification failed: {e}")

if __name__ == "__main__":
    verify_docker()
    verify_postgres()
    verify_mongodb()
