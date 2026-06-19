from database.dbConnection import get_master_db, get_company_db

def migrate_all():
    master = get_master_db()
    c = master.cursor(dictionary=True)
    c.execute("SELECT company_code FROM companies")
    companies = c.fetchall()
    c.close()
    master.close()

    for cmp in companies:
        db_name = f"sahaj_cmp_{cmp['company_code']}"
        try:
            cdb = get_company_db(db_name)
            if cdb:
                cc = cdb.cursor()
                try:
                    cc.execute("ALTER TABLE normalized_knowledge ADD COLUMN workspace_id INT NULL")
                    cdb.commit()
                    print(f"Added workspace_id to {db_name}.normalized_knowledge")
                except Exception as e:
                    if "Duplicate column name" in str(e):
                        print(f"workspace_id already exists in {db_name}.normalized_knowledge")
                    else:
                        print(f"Error altering {db_name}.normalized_knowledge: {e}")
                cc.close()
                cdb.close()
        except Exception as e:
            print(f"Could not connect to {db_name}: {e}")

if __name__ == "__main__":
    migrate_all()
