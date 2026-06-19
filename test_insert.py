import os
import requests

def test_upload():
    url = "http://localhost:3008/upload_files_new"
    
    from database.dbConnection import get_master_db
    
    db = get_master_db()
    c = db.cursor(dictionary=True)
    c.execute("SELECT session_id, user_id, company_db_name FROM user_company_sessions LIMIT 1")
    row = c.fetchone()
    if not row:
        print("No sessions found")
        return
        
    workspace_id = '1'
    schema = [{"column": "col1", "datatype": "VARCHAR(255)", "primary": True}, {"column": "col2", "datatype": "VARCHAR(255)"}]
    
    # 1. CREATE TABLE
    data_create = {
        "action": "create_table",
        "session_id": row["session_id"],
        "created_by": row["user_id"],
        "workspace_id": str(workspace_id),
        "file_name": "test_dummy.csv",
        "table_name": "test_dummy_table",
        "schema": schema
    }
    print("Creating table with:", data_create)
    res_create = requests.post(url, json=data_create)
    print("Create Table Response:", res_create.status_code, res_create.text)

    # 2. INSERT DATA
    data_insert = {
        "action": "insert_data",
        "session_id": row["session_id"],
        "created_by": row["user_id"],
        "workspace_id": str(workspace_id),
        "file_name": "test_dummy.csv",
        "table_name": "test_dummy_table",
        "is_existing": False,
        "schema": schema
    }
    print("Inserting data with:", data_insert)
    res_insert = requests.post(url, json=data_insert)
    print("Insert Data Response:", res_insert.status_code, res_insert.text)

if __name__ == '__main__':
    test_upload()
