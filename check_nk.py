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
    
    # Check schema of normalized_knowledge
    c.execute(f"DESCRIBE `{company_db}`.normalized_knowledge")
    rows = c.fetchall()
    print("Columns in normalized_knowledge:")
    for r in rows:
        print(r['Field'], r['Type'])
        
    c.close()
    db.close()

if __name__ == '__main__':
    main()
