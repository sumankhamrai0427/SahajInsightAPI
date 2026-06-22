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
def _create_master_db_connection():
    try:
        conn = mysql.connector.connect(
            **MYSQL_CONFIG,
            database="sahaj_master"
        )
        print("Master Database connection established.")
        return conn
    except mysql.connector.Error as err:
        raise Exception(f"Master DB connection error: {err}")

def get_master_db():
    if has_request_context():
        master_db = getattr(g, '_master_db', None)
        if master_db is None or not master_db.is_connected():
            master_db = _create_master_db_connection()
            g._master_db = master_db
        return master_db
    return _create_master_db_connection()

# ---------- COMPANY DB CONNECTION ----------
def _create_company_db_connection(company_db_name):
    try:
        conn = mysql.connector.connect(
            **MYSQL_CONFIG,
            database=company_db_name
        )
        return conn
    except mysql.connector.Error as err:
        raise Exception(f"Company DB connection error: {err}")

def get_company_db(company_db_name):
    if has_request_context():
        if not hasattr(g, '_company_dbs'):
            g._company_dbs = {}
        company_db = g._company_dbs.get(company_db_name)
        if company_db is None or not company_db.is_connected():
            company_db = _create_company_db_connection(company_db_name)
            g._company_dbs[company_db_name] = company_db
        return company_db
    return _create_company_db_connection(company_db_name)

# ---------- TEARDOWN FUNCTION ----------
def teardown_db(exception=None):
    """
    Closes any database connections cached on Flask's g object at the end of a request context.
    """
    if has_request_context():
        # Close master db connection
        master_db = getattr(g, '_master_db', None)
        if master_db is not None:
            try:
                master_db.close()
                print("Master DB connection closed in teardown.")
            except Exception:
                pass
            g._master_db = None

        # Close all cached company db connections
        company_dbs = getattr(g, '_company_dbs', None)
        if company_dbs is not None:
            for db_name, conn in list(company_dbs.items()):
                if conn is not None:
                    try:
                        conn.close()
                    except Exception:
                        pass
            g._company_dbs = None

        # Also close g.company_db if middleware left it open and not in caching dict
        company_db = getattr(g, 'company_db', None)
        if company_db is not None:
            try:
                company_db.close()
            except Exception:
                pass
            g.company_db = None

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
