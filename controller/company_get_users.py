from flask import request
from database.dbConnection import get_master_db, get_company_db
from helper.helperFunctions import build_response


def get_company_users_controller():
    master = cur = company_db = ccur = None
    try:
        data = request.get_json() or {}

        session_id   = data.get("session_id")
        created_by   = data.get("created_by")
        company_code = data.get("company_code")

        if not all([session_id, created_by, company_code]):
            return build_response(False, "Required fields missing", 400)

        # ===============================
        # STEP 1: MASTER DB → COMPANY
        # ===============================
        master = get_master_db()
        cur = master.cursor(dictionary=True)

        cur.execute("""
            SELECT company_db_name
            FROM companies
            WHERE company_code=%s
              AND is_active=1
              AND is_deleted=0
        """, (company_code,))
        company = cur.fetchone()

        if not company:
            return build_response(False, "Company not found", 404)

        # ===============================
        # STEP 2: COMPANY DB + SESSION
        # ===============================
        company_db = get_company_db(company["company_db_name"])
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

        # ===============================
        # STEP 3: GET USERS ONLY
        # ===============================
        ccur.execute("""
            SELECT
                u.id,
                u.user_id,
                u.full_name,
                u.email,
                u.phone_number,
                u.address,
                u.is_active,
                u.created_at
            FROM users u
            JOIN user_roles r ON r.id = u.app_role_id
            WHERE u.is_deleted = 0
            ORDER BY u.created_at DESC
        """)

        users = ccur.fetchall()

        return build_response(
            True,
            "Users fetched successfully",
            200,
            users
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
