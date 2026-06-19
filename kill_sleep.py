from database.dbConnection import get_master_db
db = get_master_db()
c = db.cursor(dictionary=True)
c.execute('SHOW FULL PROCESSLIST')
for row in c.fetchall():
    if row['Time'] > 60 and row['Command'] == 'Sleep':
        try:
            db.cursor().execute(f"KILL {row['Id']}")
            print(f"Killed {row['Id']}")
        except Exception as e:
            print(f"Failed to kill {row['Id']}: {e}")
db.close()
