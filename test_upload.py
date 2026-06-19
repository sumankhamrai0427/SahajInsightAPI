import os
import requests

def test_upload():
    # Make a request to the backend to upload a test file
    url = "http://localhost:3008/upload_files_new"
    
    # create a dummy file
    with open("test_dummy.csv", "w") as f:
        f.write("col1,col2\nval1,val2\n")
        
    files = [
        ('files', ('test_dummy.csv', open('test_dummy.csv', 'rb'), 'text/csv'))
    ]
    
    from database.dbConnection import get_master_db
    db = get_master_db()
    c = db.cursor(dictionary=True)
    c.execute("SELECT session_id, user_id, company_db_name FROM user_company_sessions LIMIT 1")
    row = c.fetchone()
    if not row:
        print("No sessions found")
        return
        
    data = {
        "action": "upload",
        "session_id": row["session_id"],
        "created_by": row["user_id"],
        "workspace_id": "1",
        "has_header": "true"
    }
    
    print("Uploading with:", data)
    res = requests.post(url, data=data, files=files)
    print("Response Status:", res.status_code)
    print("Response Body:", res.text)

if __name__ == '__main__':
    test_upload()
