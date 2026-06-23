from flask import request
import uuid, bcrypt
from database.dbConnection import get_master_db, get_company_db
from helper.helperFunctions import build_response
import os
from dotenv import load_dotenv
load_dotenv()   
BASE_URL = os.getenv("BASE_URL")

def company_login_controller():
    data = request.get_json() or {}

    company_code = data.get("company_code")
    email = data.get("user_email")
    password = data.get("password")

    if not all([company_code, email, password]):
        return build_response(False, "company_code, email & password required", 400)

    master = None
    cur = None
    company_db = None
    ccur = None
    try:
        master = get_master_db()
        cur = master.cursor(dictionary=True, buffered=True)

        cur.execute(
            """
       SELECT 
        c.id,
        c.company_name,
        c.company_code,
        c.company_email,
        c.address,
        c.subscription_type,
        c.from_date,
        c.to_date,
        c.company_db_name,
        c.phone_number,
        c.company_logo,
        c.city,
        c.country AS country_code,
        co.country_name,
        c.pin_code
    FROM companies c
    LEFT JOIN countries co 
        ON co.country_code = c.country
    WHERE c.company_code = %s
      AND c.is_active = 1
        """,
            (company_code,),
        )
        company = cur.fetchone()

        if not company:
            return build_response(False, "Company not found", 404)
        cur.close()
        cur = None

        company_db = get_company_db(company["company_db_name"])
        ccur = company_db.cursor(dictionary=True)

        ccur.execute(
            """
            SELECT u.user_id, u.password_hash, u.plain_password,u.session_id, ur.role_name, u.full_name,
            u.email
            FROM users u
            JOIN user_roles ur ON ur.id = u.app_role_id
            WHERE (u.user_id=%s OR u.email=%s) AND u.plain_password=%s
        """,
            (email, email, password),
        )
        user = ccur.fetchone()

        if not user:
            return build_response(False, "Invalid credentials", 401)
            
        session_id = user["session_id"] or str(uuid.uuid4())
        ccur.execute(
            "UPDATE users SET session_id=%s WHERE user_id=%s", (session_id, user["user_id"])
        )
        company_db.commit()
        ccur.close()
        ccur = None
        company_db.close()
        company_db = None 

        mcur = master.cursor()
        mcur.execute("""
            INSERT INTO user_company_sessions
            (session_id, user_id, company_id, company_db_name)
            VALUES (%s,%s,%s,%s)
            ON DUPLICATE KEY UPDATE
                company_db_name = VALUES(company_db_name)
        """, (
            session_id,
            user["user_id"],
            company["id"],
            company["company_db_name"]
        ))
        master.commit()
        mcur.close()
        master.close()
        master = None

        # ---- build full logo url for PDF ----
        base_url = BASE_URL
        logo_path = company["company_logo"]        # /uploads/companies/...

        company_logo_url = (
                f"{base_url}{logo_path}"
                if logo_path else None
            )

        return build_response(
            True,
            "Login successful",
            200,
            {
                # ---------- USER ----------
                "user_id": user["user_id"],
                "full_name": user["full_name"],
                "user_email": user["email"],
                "role": user["role_name"],
                "session_id": session_id,
                # ---------- COMPANY ----------
                "company_id": company["id"],
                "company_name": company["company_name"],
                "company_code": company["company_code"],
                "company_email": company["company_email"],
                "company_address": company["address"],
                "company_logo": company["company_logo"],
                "company_logo_url": company_logo_url,
                "company_phone": company["phone_number"],
                "subscription_type": company["subscription_type"],
                "subscription_from": str(company["from_date"]),
                "subscription_to": str(company["to_date"]),
                "city": company["city"],
                "country": company["country_name"],
                "pin_code": company["pin_code"]
            },
        )
    finally:
        for x in [ccur, company_db, cur, master]:
            if x is not None:
                try:
                    x.close()
                except Exception:
                    pass
