import sys
import os
from database.dbConnection import get_master_db

def main():
    db = get_master_db()
    c = db.cursor(dictionary=True)
    c.execute("SELECT company_db_name FROM companies LIMIT 1")
    row = c.fetchone()
    if not row:
        print("No companies found")
        return
    company_db = row['company_db_name']
    
    # Query schema
    c.execute(f"SELECT COLUMN_NAME, TABLE_NAME FROM INFORMATION_SCHEMA.COLUMNS WHERE TABLE_SCHEMA = '{company_db}' AND TABLE_NAME IN ('uploaded_files', 'normalized_knowledge', 'query_history', 'saved_reports')")
    cols = c.fetchall()
    
    schema = {}
    for col in cols:
        t = col['TABLE_NAME']
        cn = col['COLUMN_NAME']
        if t not in schema:
            schema[t] = []
        schema[t].append(cn)
        
    for t, columns in schema.items():
        print(f"Table: {t}")
        print(f"Columns: {', '.join(columns)}")
        print()
    
    c.close()
    db.close()

if __name__ == '__main__':
    main()
