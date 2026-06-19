from database.dbConnection import get_company_db

def debug_db():
    db = get_company_db("sahaj_cmp_COMGEN002")
    c = db.cursor(dictionary=True)
    c.execute("DESCRIBE normalized_knowledge")
    ws = c.fetchall()
    for w in ws:
        print(w['Field'])
    
if __name__ == "__main__":
    debug_db()
