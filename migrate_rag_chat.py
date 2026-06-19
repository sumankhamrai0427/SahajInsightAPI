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
                    cc.execute("""
                        CREATE TABLE IF NOT EXISTS rag_chat_history (
                            id INT AUTO_INCREMENT PRIMARY KEY,
                            session_id VARCHAR(100),
                            user_id VARCHAR(100),
                            workspace_id INT,
                            user_query TEXT,
                            ai_response TEXT,
                            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                        )
                    """)
                    cdb.commit()
                    print(f"Created rag_chat_history in {db_name}")
                except Exception as e:
                    print(f"Error creating in {db_name}: {e}")
                cc.close()
                cdb.close()
        except Exception as e:
            print(f"Could not connect to {db_name}: {e}")

if __name__ == "__main__":
    migrate_all()
