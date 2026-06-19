import os
from database.dbConnection import get_master_db
import pandas as pd
from controller.upload_file_new import clean_column_names

def main():
    db = get_master_db()
    c = db.cursor(dictionary=True)
    c.execute("SELECT company_db_name FROM companies LIMIT 1")
    row = c.fetchone()
    if not row:
        print("No companies found")
        return
    company_db = row['company_db_name']
    
    # Query uploaded files
    c.execute(f"SELECT file_name, table_name FROM `{company_db}`.uploaded_files ORDER BY created_at DESC LIMIT 1")
    f_row = c.fetchone()
    if not f_row:
        print("No files uploaded")
        return
        
    print(f"Last uploaded file: {f_row['file_name']}, Table: {f_row['table_name']}")
    
    # Check db columns
    c.execute(f"SHOW COLUMNS FROM `{company_db}`.`{f_row['table_name']}`")
    cols = c.fetchall()
    db_cols = [col["Field"].lower() for col in cols if col["Field"].lower() != "row_hash"]
    print("DB Cols:", db_cols)
    
    # Check CSV columns
    file_path = os.path.join("uploads", f_row['file_name'])
    if os.path.exists(file_path):
        try:
            df = pd.read_csv(file_path, nrows=5)
            csv_cols = clean_column_names(df.columns)
            csv_cols_lower = [col.lower() for col in csv_cols]
            print("CSV Cols:", csv_cols_lower)
            
            missing = [c for c in db_cols if c not in csv_cols_lower]
            extra = [c for c in csv_cols_lower if c not in db_cols]
            print("Missing in CSV:", missing)
            print("Extra in CSV:", extra)
        except Exception as e:
            print("Error reading CSV:", e)
    else:
        print(f"File {file_path} not found")
        
    c.close()
    db.close()

if __name__ == '__main__':
    main()
