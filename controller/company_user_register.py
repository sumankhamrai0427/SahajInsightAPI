from flask import request
import uuid, bcrypt
from dotenv import load_dotenv
from database.dbConnection import get_master_db, get_company_db
from helper.helperFunctions import build_response, generate_user_id

import os
load_dotenv()


def company_user_register_controller():
    master = cur = company_db = ccur = None
    try:
        data = request.get_json() or {}

        # ================================
        # COMMON INPUTS
        # ================================
        session_id   = data.get("session_id")
        created_by  = data.get("created_by")
        company_code = data.get("company_code")

        user_db_id  = data.get("id")       
        name        = data.get("user_name")
        email       = data.get("user_email")
        password    = data.get("user_password")  
        phone       = data.get("phone_number")
        address     = data.get("address")   

        if not all([session_id, created_by, company_code]):
            return build_response(False, "Required fields missing", 400)

        # =================================================
        # STEP 1: COMPANY RESOLVE (MASTER DB)
        # =================================================
        master = get_master_db()
        cur = master.cursor(dictionary=True)

        cur.execute("""
            SELECT id, company_db_name, company_name
            FROM companies
            WHERE company_code=%s
              AND is_active=1
              AND is_deleted=0
        """, (company_code,))
        company = cur.fetchone()

        if not company:
            return build_response(False, "Company not found", 404)

        company_id = company["id"]
        company_db_name = company["company_db_name"]
        company_name = company["company_name"]
        # =================================================
        # STEP 2: COMPANY DB + SESSION VALIDATION
        # =================================================
        company_db = get_company_db(company_db_name)
        ccur = company_db.cursor(dictionary=True)

        ccur.execute("""
            SELECT user_id
            FROM users
            WHERE user_id=%s
              AND session_id=%s
              AND is_deleted=0
        """, (created_by, session_id))

        if not ccur.fetchone():
            return build_response(False, "Invalid session", 403)

        # =================================================
        # STEP 3: ROLE (user)
        # =================================================
        ccur.execute("SELECT id FROM user_roles WHERE role_name='user'")
        role = ccur.fetchone()

        if not role:
            return build_response(False, "User role not found", 500)

        role_id = role["id"]

        # =================================================
        # UPDATE USER
        # =================================================
        if user_db_id:
            ccur.execute("""
                UPDATE users
                SET
                    phone_number=%s,
                    address=%s,
                    updated_by=%s,
                    updated_at=NOW()
                WHERE id=%s
                  AND is_deleted=0
            """, (
                phone,
                address,
                created_by,
                user_db_id
            ))

            company_db.commit()
            return build_response(True, "User updated successfully", 200)

        # =================================================
        #  ADD USER
        # =================================================
        if not all([name, email, password]):
            return build_response(False, "Required fields missing", 400)

        # duplicate email
        ccur.execute("""
            SELECT id FROM users
            WHERE email=%s AND is_deleted=0
        """, (email,))
        if ccur.fetchone():
            return build_response(False, "Email already exists", 400)

        user_id = generate_user_id(name.split()[0])
        password_hash = bcrypt.hashpw(
            password.encode("utf-8"),
            bcrypt.gensalt()
        ).decode("utf-8")

        user_session_id = str(uuid.uuid4())

        ccur.execute("""
            INSERT INTO users (
                user_id,
                full_name,
                email,
                phone_number,
                address,
                password_hash,
                plain_password,
                app_role_id,
                company_id,
                session_id,
                created_by,
                created_at
            )
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
        """, (
            user_id,
            name,
            email,
            phone,
            address,
            password_hash,
            password,
            role_id,
            company_id,
            user_session_id,
            created_by
        ))

        company_db.commit()
       
        return build_response(
            True,
            "User created successfully",
            200,
            {
                "user_id": user_id,
                "user_email": email,
                "company_code": company_code
            }
        )

    except Exception as e:
        return build_response(False, "Server error", 500, {"error": str(e)})

    finally:
        for x in [ccur, company_db, cur, master]:
            try:
                if x:
                    x.close()
            except:
                pass
