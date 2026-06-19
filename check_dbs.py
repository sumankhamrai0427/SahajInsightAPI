import os
from database.dbConnection import get_company_db

dbs = ['sahaj_cmp_ABCGEN001', 'sahaj_cmp_BRCGEN001', 'sahaj_cmp_RTYGEN001', 'sahaj_cmp_ABCGEN002']
for d in dbs:
    try:
        db = get_company_db(d)
        c = db.cursor(dictionary=True)
        c.execute("SELECT COUNT(*) as cnt FROM uploaded_files")
        print(f"{d}: {c.fetchone()['cnt']} uploaded files")
        db.close()
    except Exception as e:
        print(f"Failed {d}: {e}")
