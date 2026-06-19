from flask import request, g
from database.dbConnection import get_master_db, get_company_db

def attach_company_db():
    skip_routes = (
        # "hello_world",
        # "superadmin_login",
        # "company_login",
        # "admin_company_register_route",
        # "admin_company_admin_register_route",
        "/",
        "/superadmin/login",
        "/company/login",
        "/admin/company_register",
        "/admin/company/admin_register",
        "/admin/get_companies",
        "/admin/create_seo"
        "/admin/update_seo"
        "/admin/delete_seo"
        "/admin/get_seo_list",
        "/admin/get_seo_by_path"
     
    
    )

    if request.path  in skip_routes:
        return

    # 🔥 ONLY session_id
    if request.content_type and request.content_type.startswith("multipart"):
        session_id = request.form.get("session_id")
    else:
        data = request.get_json(silent=True) or {}
        session_id = data.get("session_id")

    if not session_id:
        return

    master = get_master_db()
    cur = master.cursor(dictionary=True)

    cur.execute("""
        SELECT user_id, company_db_name
        FROM user_company_sessions
        WHERE session_id = %s
        LIMIT 1
    """, (session_id,))

    row = cur.fetchone()
    cur.close()
    master.close()

    if row:
        g.created_by = row["user_id"]
        g.company_db = get_company_db(row["company_db_name"])

