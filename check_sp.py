import os
from database.dbConnection import get_master_db

def main():
    db = get_master_db()
    c = db.cursor(dictionary=True)
    c.execute("SELECT company_db_name FROM companies LIMIT 1")
    row = c.fetchone()
    if not row:
        return
    company_db = row['company_db_name']
    
    c.execute(f"SHOW CREATE PROCEDURE `{company_db}`.sp_insert_uploaded_file")
    res = c.fetchone()
    
    with open("sp_out.txt", "w", encoding="utf-8") as f:
        f.write(res['Create Procedure'])
    
    c.close()
    db.close()

if __name__ == '__main__':
    main()
