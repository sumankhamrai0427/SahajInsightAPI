import os
from dotenv import load_dotenv
import mysql.connector

load_dotenv()

conn = mysql.connector.connect(
    host=os.getenv("DB_HOST"),
    user=os.getenv("DB_USER"),
    password=os.getenv("DB_PASSWORD")
)
cur = conn.cursor(dictionary=True)
cur.execute("SHOW DATABASES LIKE 'sahaj_cmp_%'")
dbs = [list(x.values())[0] for x in cur.fetchall()]
for db in dbs:
    try:
        cur.execute(f"USE {db}")
        cur.execute("SELECT * FROM user_roles")
        roles = cur.fetchall()
        print(f"{db}: {roles}")
    except Exception as e:
        print(f"Error on {db}: {e}")
