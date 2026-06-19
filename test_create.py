import os
import requests

def test_upload():
    # Make a request to the backend to upload a test file
    url = "http://localhost:3008/upload_files_new"
    
    from database.dbConnection import get_master_db
    import json
    
    db = get_master_db()
    c = db.cursor(dictionary=True)
    c.execute("SELECT session_id, user_id, company_db_name FROM user_company_sessions LIMIT 1")
    row = c.fetchone()
    if not row:
        print("No sessions found")
        return
        
    workspace_id = '1'
    
    # 2. CREATE TABLE
    data_create = {
        "action": "create_table",
        "session_id": row["session_id"],
        "created_by": row["user_id"],
        "workspace_id": str(workspace_id),
        "file_name": "test_dummy.csv",
        "table_name": "test_dummy_table",
        "schema": json.dumps([{"column": "col1", "type": "VARCHAR(255)"}, {"column": "col2", "type": "VARCHAR(255)"}])
    }
    print("Creating table with:", data_create)
    res_create = requests.post(url, json=data_create)
    print("Create Table Response:", res_create.status_code, res_create.text)

if __name__ == '__main__':
    test_upload()
