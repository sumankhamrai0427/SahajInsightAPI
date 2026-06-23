import os
import sys
import mysql.connector
from dotenv import load_dotenv

# Add current directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database.dbConnection import MYSQL_CONFIG

def main():
    print("Database Cleanup Script Started...")
    
    # 1. Connect to MySQL server
    try:
        conn = mysql.connector.connect(**MYSQL_CONFIG)
        cursor = conn.cursor(dictionary=True)
    except Exception as e:
        print(f"Failed to connect to MySQL: {e}")
        return

    try:
        # 2. Get list of all databases on MySQL
        cursor.execute("SHOW DATABASES")
        all_dbs = [row[list(row.keys())[0]] for row in cursor.fetchall()]
        
        # 3. Get all company databases from sahaj_master.companies
        company_dbs_from_metadata = []
        try:
            cursor.execute("SELECT company_db_name FROM sahaj_master.companies WHERE company_db_name IS NOT NULL")
            company_dbs_from_metadata = [row["company_db_name"] for row in cursor.fetchall()]
        except Exception as e:
            print(f"Warning: Could not fetch company databases from companies table: {e}")

        # Combine: databases starting with sahaj_cmp_ OR listed in metadata
        dbs_to_drop = set()
        for db in all_dbs:
            if db.startswith("sahaj_cmp_") or db in company_dbs_from_metadata:
                dbs_to_drop.add(db)
                
        # 4. Drop company databases
        print(f"\nFound {len(dbs_to_drop)} company database(s) to drop.")
        for db_name in dbs_to_drop:
            try:
                print(f"  Dropping database: {db_name}...")
                cursor.execute(f"DROP DATABASE IF EXISTS {db_name}")
                print(f"  Successfully dropped {db_name}.")
            except Exception as e:
                print(f"  Error dropping database {db_name}: {e}")
                
        # 5. Connect to sahaj_master and truncate non-core tables
        print("\nConnecting to master database 'sahaj_master'...")
        cursor.execute("USE sahaj_master")
        
        # Core metadata tables to KEEP (Do NOT truncate)
        core_tables = {"companies", "users", "app_roles", "countries", "seo_metadata"}
        
        # Dynamic tables to TRUNCATE
        tables_to_truncate = ["user_company_sessions", "workspace_users", "workspaces", "contact_messages"]
        
        # Temporarily disable foreign keys for truncation
        print("\nDisabling foreign key checks...")
        cursor.execute("SET FOREIGN_KEY_CHECKS = 0")
        
        # Truncate tables
        for table in tables_to_truncate:
            try:
                print(f"  Truncating table: {table}...")
                cursor.execute(f"TRUNCATE TABLE {table}")
                print(f"  Successfully truncated {table}.")
            except Exception as e:
                print(f"  Error truncating table {table}: {e}")
                
        # Re-enable foreign keys
        print("Re-enabling foreign key checks...")
        cursor.execute("SET FOREIGN_KEY_CHECKS = 1")
        
        conn.commit()
        print("\nDatabase cleanup completed successfully!")
        
    except Exception as e:
        print(f"\nAn error occurred during cleanup: {e}")
    finally:
        cursor.close()
        conn.close()

if __name__ == "__main__":
    main()
