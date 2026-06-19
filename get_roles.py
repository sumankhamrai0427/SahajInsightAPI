import os
from dotenv import load_dotenv
import mysql.connector

load_dotenv()

DB_HOST = os.getenv("DB_HOST")
DB_USER = os.getenv("DB_USER")
DB_PASS = os.getenv("DB_PASSWORD")

try:
    conn = mysql.connector.connect(
        host=DB_HOST,
        user=DB_USER,
        password=DB_PASS
    )
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SHOW DATABASES LIKE '%company%';")
    dbs = cursor.fetchall()
    if dbs:
        db_name = list(dbs[0].values())[0]
        cursor.execute(f"USE {db_name};")
        cursor.execute("SELECT * FROM user_roles;")
        roles = cursor.fetchall()
        for r in roles:
            print(r)
except Exception as e:
    print(e)
