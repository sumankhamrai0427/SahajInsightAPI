from flask import request
import bcrypt
import uuid
import os

from flask.cli import load_dotenv
from database.dbConnection import get_master_db, get_company_db
from helper.helperFunctions import build_response


load_dotenv()

# ==========================================================
# ENV CONFIG
# ==========================================================
DB_HOST = os.getenv("DB_HOST")
DB_USER = os.getenv("DB_USER")
DB_PASS = os.getenv("DB_PASSWORD")


def admin_company_admin_register_controller():
    cursor = None
    master = None
    company_cursor = None
    company_conn = None

    try:
        data = request.get_json() or {}
        admin_user_id = data.get("id")
        session_id = data.get("session_id")
        created_by = data.get("created_by")  # SuperAdmin user_id

        company_code = data.get("company_code")
        admin_name = data.get("admin_name")
        admin_email = data.get("admin_email")
        admin_password = data.get("admin_password")

        admin_phone = data.get("phone_number")
        # admin_address = data.get("address")

        # --------------------------------------------------
        # BASIC VALIDATION
        # --------------------------------------------------
        if not session_id or not created_by or not company_code or not admin_name or not admin_password:
            return build_response(
                False,
                "company_code, admin_name, admin_password, session_id, created_by required",
                400
            )


        # ==================================================
        # STEP 1: SUPER ADMIN VALIDATION (MASTER DB)
        # ==================================================
        master = get_master_db()
        cursor = master.cursor(dictionary=True)

        cursor.execute(
            """
            SELECT u.user_id
            FROM users u
            JOIN app_roles ar ON ar.id = u.app_role_id
            WHERE u.user_id = %s
              AND u.session_id = %s
              AND ar.role_name = 'superadmin'
        """,
            (created_by, session_id),
        )

        superadmin = cursor.fetchone()

        if not superadmin:
            return build_response(
                False, "Unauthorized: Only SuperAdmin can create Company Admin", 403
            )

        # ==================================================
        # STEP 2: FETCH COMPANY INFO (MASTER DB)
        # ==================================================
        cursor.execute(
            """
            SELECT id, company_name, company_email, company_db_name
            FROM companies
            WHERE company_code = %s
              AND is_active = 1 AND is_deleted = 0
        """,
            (company_code,),
        )

        company = cursor.fetchone()

        if not company:
            return build_response(False, "Company not found", 404)

        company_id = company["id"]
        company_db_name = company["company_db_name"]
        company_email = company["company_email"]  # ✅ NOW AVAILABLE
        company_name = company["company_name"]
        # ==================================================
        # STEP 3: HASH PASSWORD
        # ==================================================
        hashed_password = bcrypt.hashpw(
            admin_password.encode("utf-8"), bcrypt.gensalt()
        ).decode("utf-8")

        plain_password = admin_password

        # ==================================================
        # STEP 4: CONNECT COMPANY DB
        # ==================================================
        company_conn = get_company_db(company_db_name)
        company_cursor = company_conn.cursor(dictionary=True)

        # ==================================================
        # STEP 5: FETCH CompanyAdmin ROLE (company DB)
        # ==================================================
        company_cursor.execute(
            """
            SELECT id
            FROM user_roles
            WHERE role_name = 'companyadmin'
        """
        )
        role = company_cursor.fetchone()

        if role:
            company_admin_role_id = role["id"]
        else:
            # Fallback to 1 as per user_roles configuration
            company_admin_role_id = 1
        # ==================================================
        #  UPDATE MODE (admin_user_id আসলে)
        # ==================================================
        # if admin_user_id:
        #     company_cursor.execute(
        #         """
        #         UPDATE users
        #         SET
        #             email = %s,
        #             phone_number = %s,
        #             address = %s,
        #             updated_by = %s,
        #             updated_at = NOW()
        #         WHERE id = %s AND is_deleted = 0
        #     """,
        #         (admin_email, admin_phone, admin_address, created_by, admin_user_id),

        if admin_user_id:
            company_cursor.execute("""
            SELECT id FROM users
            WHERE user_id = %s
            AND id != %s
            AND is_deleted = 0
        """, (admin_name, admin_user_id))

            if company_cursor.fetchone():
                return build_response(
                    False,
                    "This user name already exists",
                    400
                )
            company_cursor.execute("""
                UPDATE users
                SET
                    user_id = %s,             
                    full_name = %s,
                    email = %s,
                    phone_number = %s,
                    plain_password = %s,
                    password_hash = %s,
                    updated_by = %s,
                    updated_at = NOW()
                WHERE id = %s AND is_deleted = 0
            """, (
                admin_name,
                admin_name, # saving to full_name as well
                admin_email,
                admin_phone,
                admin_password,
                hashed_password,
                created_by,
                admin_user_id
            ))
            company_conn.commit()
            return build_response(True, "Company Admin updated successfully", 200)




        # ==================================================
        # STEP 5.5: CHECK IF COMPANY ADMIN ALREADY EXISTS
        # (One Company → One CompanyAdmin rule)
        # ==================================================
        company_cursor.execute(
            """
            SELECT id
            FROM users
            WHERE app_role_id = %s AND company_id = %s AND is_deleted = 0
        """,
            (company_admin_role_id,company_id),
        )

        if company_cursor.fetchone():
            return build_response(
                False, "companyadmin already exists for this company", 400
            )

        # ==================================================
        # STEP 6: CHECK DUPLICATE ADMIN EMAIL (company DB)
        # ==================================================
        company_cursor.execute(
            """
            SELECT id FROM users WHERE user_id = %s AND is_deleted = 0
        """,
            (admin_name,),
        )

        if company_cursor.fetchone():
            return build_response(
                False, "This user name already exists", 400
            )

        # ==================================================
        # STEP 6.5: GENERATE SESSION ID FOR COMPANY ADMIN
        # ==================================================
        admin_session_id = str(uuid.uuid4())

        # ==================================================
        # STEP 7: INSERT COMPANY ADMIN (company DB)
        # ==================================================
        # company_cursor.execute("""
        #     INSERT INTO users
        #     (
        #         user_id,
        #         full_name,
        #         email,
        #         phone_number,
        #         address,
        #         password_hash,
        #         app_role_id,
        #         company_id,
        #         session_id,
        #         created_by,
        #         created_at
        #     )
        #     VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
        # """, (
        #     f"admin_{company_code}",
        #     admin_name,
        #     admin_email,
        #     admin_phone,
        #     admin_address,
        #     hashed_password,
        #     company_admin_role_id,
        #     company_id,
        #     admin_session_id,
        #     created_by
        # ))

        company_cursor.execute(
            """
                INSERT INTO users
                (
                    user_id,
                    full_name,
                    email,
                    phone_number,
                    password_hash,
                    plain_password,
                    app_role_id,
                    company_id,
                    session_id,
                    created_by,
                    created_at
                )
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
            """, (
                admin_name,
                admin_name,
                admin_email,
                admin_phone,
                hashed_password,
                plain_password,
                company_admin_role_id,
                company_id,
                admin_session_id,
                created_by
            ),
        )

        company_conn.commit()
        return build_response(
            True,
            "Company Admin registered successfully",
            200,
            extra={
                "company_code": company_code,
                "company_db": company_db_name,
                "admin_user_id": admin_name,
                "admin_name": admin_name,
            },
        )

    except Exception as e:
        return build_response(False, "Server error", 500, data={"error": str(e)})

    finally:
        try:
            if company_cursor:
                company_cursor.close()
            if company_conn:
                company_conn.close()
            if cursor:
                cursor.close()
            if master:
                master.close()
        except:
            pass
