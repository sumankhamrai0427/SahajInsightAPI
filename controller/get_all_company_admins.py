from database.dbConnection import get_master_db, get_company_db
from helper.helperFunctions import build_response

def get_all_company_admins_controller():
    try:
        master = get_master_db()
        mcur = master.cursor(dictionary=True)

        # STEP 1: Get all active companies
        mcur.execute("""
            SELECT 
                id AS company_id,
                company_code,
                company_name,
                company_db_name
            FROM companies
            WHERE is_active = 1
              AND is_deleted = 0
        """)
        companies = mcur.fetchall()

        result = []

        #  STEP 2: Loop each company DB
        for c in companies:
            try:
                company_db = get_company_db(c["company_db_name"])
                ccur = company_db.cursor(dictionary=True)

                #  Fetch company admin
                ccur.execute("""
                    SELECT
                        u.id,
                        u.user_id,
                        u.full_name,
                        u.email,
                        u.phone_number,
                        u.address,
                        u.is_active,
                        u.plain_password,
                        u.created_at
                    FROM users u
                    JOIN user_roles r ON u.app_role_id = r.id
                    WHERE u.company_id = %s
                    AND u.is_deleted = 0
                    AND r.role_name = 'companyadmin'
                """, (c["company_id"],))

                admins = ccur.fetchall()

                # if admin:
                #     result.append({
                #         "company_id": c["company_id"],
                #         "company_code": c["company_code"],
                #         "company_name": c["company_name"],
                #         "company_db": c["company_db_name"],

                #         "admin_user_id": admin["user_id"],
                #         "admin_name": admin["user_id"],      # user_id == admin_name
                #         "plain_password": admin["plain_password"],  # UI will show this
                #         "created_at": admin["created_at"],
                #         "id": admin["id"]
                #     })

                if not admins:
                    result.append({
                        "company_id": c["company_id"],
                        "company_code": c["company_code"],
                        "company_name": c["company_name"],
                        "company_db": c["company_db_name"],
                        "admin_user_id": None,
                        "admin_name": None,
                        "admin_email": None,
                        "phone_number": None,
                        "address": None,
                        "is_active": None,
                        "plain_password": None,
                        "created_at": None,
                        "id": None
                    })
                else:
                    for admin in admins:
                        result.append({
                            "company_id": c["company_id"],
                            "company_code": c["company_code"],
                            "company_name": c["company_name"],
                            "company_db": c["company_db_name"],
                            "admin_user_id": admin["user_id"],
                            "admin_name": admin["full_name"] or admin["user_id"],
                            "admin_email": admin["email"],
                            "phone_number": admin["phone_number"],
                            "address": admin["address"],
                            "is_active": admin["is_active"],
                            "plain_password": admin["plain_password"],
                            "created_at": admin["created_at"],
                            "id": admin["id"]
                        })
                ccur.close()
                company_db.close()

            except Exception as inner_err:
                # If company DB missing / corrupted -> include company with no admins
                result.append({
                    "company_id": c["company_id"],
                    "company_code": c["company_code"],
                    "company_name": c["company_name"],
                    "company_db": c["company_db_name"],
                    "admin_user_id": None,
                    "admin_name": None,
                    "admin_email": None,
                    "phone_number": None,
                    "address": None,
                    "is_active": None,
                    "plain_password": None,
                    "created_at": None,
                    "id": None
                })
                continue

        mcur.close()
        master.close()

        return build_response(
            True,
            "Company users list fetched successfully",
            200,
            data=result
        )

    except Exception as e:
        return build_response(
            False,
            "Server error",
            500,
            data={"error": str(e)}
        )
