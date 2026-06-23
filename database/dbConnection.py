import os
from dotenv import load_dotenv
import mysql.connector
from flask import g, has_request_context
# ---------- Load Environment Variables ----------
load_dotenv()
# ---------- Database Configuration ----------
MYSQL_CONFIG = {
    "user": os.getenv("DB_USER"),
    "password": os.getenv("DB_PASSWORD", ""),
    "host": os.getenv("DB_HOST"),
    "port": int(os.getenv("DB_PORT"))  # default 3306 if not set
    # "database": os.getenv("DB_NAME")
}

# ---------- MASTER DB CONNECTION ----------
def get_master_db():
    if has_request_context():
        if hasattr(g, 'master_db'):
            try:
                if g.master_db.is_connected():
                    return g.master_db
            except Exception:
                pass
    try:
        conn = mysql.connector.connect(
            **MYSQL_CONFIG,
            database="sahaj_master",
            pool_name="master_pool",
            pool_size=10,
            pool_reset_session=True
        )
        if has_request_context():
            g.master_db = conn
        return conn
    except mysql.connector.Error as err:
        raise Exception(f"Master DB connection error: {err}")

# ---------- COMPANY DB CONNECTION ----------
def get_company_db(company_db_name):
    if has_request_context():
        if not hasattr(g, 'company_dbs'):
            g.company_dbs = {}
        if company_db_name in g.company_dbs:
            try:
                if g.company_dbs[company_db_name].is_connected():
                    return g.company_dbs[company_db_name]
            except Exception:
                pass
    try:
        conn = mysql.connector.connect(
            **MYSQL_CONFIG,
            database=company_db_name,
            pool_name=f"pool_{company_db_name}",
            pool_size=10,
            pool_reset_session=True
        )
        if has_request_context():
            g.company_dbs[company_db_name] = conn
            g.company_db = conn
        return conn
    except mysql.connector.Error as err:
        raise Exception(f"Company DB connection error: {err}")
    
# ---------- BACKWARD COMPATIBLE FUNCTION ----------
def get_db_connection():
    """
    This keeps old controllers working.
    If request context exists → use company DB
    Else → fallback to master DB
    """
    if has_request_context() and hasattr(g, "company_db"):
        return g.company_db

    # fallback (safety)
    return get_master_db()
