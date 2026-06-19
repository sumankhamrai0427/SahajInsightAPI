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
    try:
        conn = mysql.connector.connect(
            **MYSQL_CONFIG,
            database="sahaj_master"
        )
        print("Master Database connection established.")
        return conn
    except mysql.connector.Error as err:
        raise Exception(f"Master DB connection error: {err}")

# ---------- COMPANY DB CONNECTION ----------
def get_company_db(company_db_name):
    try:
        conn = mysql.connector.connect(
            **MYSQL_CONFIG,
            database=company_db_name
        )
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
