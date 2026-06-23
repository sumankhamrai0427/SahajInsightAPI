# controller/auth_superadmin_login.py
from flask import request
import uuid, bcrypt
from database.dbConnection import get_master_db
from helper.helperFunctions import build_response

def superadmin_login_controller():
    data = request.get_json() or {}

    email = data.get("user_email")
    password = data.get("password")

    if not email or not password:
        return build_response(False, "Email & password required", 400)

    db = None
    cur = None
    try:
        db = get_master_db()
        cur = db.cursor(dictionary=True)

        cur.execute("""
            SELECT u.user_id, u.password_hash, u.session_id, u.full_name
            FROM users u
            JOIN app_roles ar ON ar.id = u.app_role_id
            WHERE u.email=%s AND ar.role_name='superadmin'
        """, (email,))
        user = cur.fetchone()

        if not user:
            return build_response(False, "Invalid credentials", 401)

        if not bcrypt.checkpw(password.encode(), user["password_hash"].encode()):
            return build_response(False, "Invalid credentials", 401)

        session_id = user["session_id"] or str(uuid.uuid4())
        cur.execute(
            "UPDATE users SET session_id=%s WHERE user_id=%s",
            (session_id, user["user_id"])
        )
        db.commit()

        return build_response(True, "Login successful", 200, {
            "user_id": user["user_id"],
            "role": "superadmin",
            "session_id": session_id,
            "full_name": user["full_name"],
        })
    finally:
        if cur is not None:
            try:
                cur.close()
            except Exception:
                pass
        if db is not None:
            try:
                db.close()
            except Exception:
                pass
