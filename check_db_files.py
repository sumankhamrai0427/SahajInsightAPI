import os
from database.dbConnection import get_master_db
import json

def main():
    db = get_master_db()
    c = db.cursor(dictionary=True)
    c.execute("SELECT company_db_name FROM companies LIMIT 1")
    row = c.fetchone()
    if not row:
        return
    company_db = row['company_db_name']
    
    # Query uploaded_files
    c.execute(f"SELECT * FROM `{company_db}`.uploaded_files ORDER BY created_at DESC LIMIT 5")
    rows = c.fetchall()
    print("Recent uploaded_files:")
    for r in rows:
        print(r['file_name'], r['table_name'], r['created_by'], r.get('workspace_id'), r['data_insert_status'])
        
    c.close()
    db.close()

if __name__ == '__main__':
    main()
