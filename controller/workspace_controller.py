from flask import request
from helper.helperFunctions import build_response, format_dates_in_rows
from database.dbConnection import get_master_db, get_company_db

def _get_company_db_name(session_id, created_by):
    db = get_master_db()
    c = db.cursor(dictionary=True)
    c.execute("SELECT company_db_name FROM user_company_sessions WHERE session_id = %s AND user_id = %s", (session_id, created_by))
    session = c.fetchone()
    c.close()
    db.close()
    if session:
        return session["company_db_name"]
    return None

def create_workspace_controller():
    try:
        data = request.get_json() or {}
        workspace_name = data.get("workspace_name")
        session_id = data.get("session_id")
        created_by = data.get("created_by")
        user_email = data.get("user_email")
        
        if not workspace_name or not session_id or not created_by:
            return build_response(False, "workspace_name, session_id, and created_by are required", 400)
            
        company_db_name = _get_company_db_name(session_id, created_by)
        if not company_db_name:
            return build_response(False, "Invalid session", 401)
            
        company_db = get_company_db(company_db_name)
        c = company_db.cursor(dictionary=True)
        
        # Look up email if not provided
        if not user_email:
            c.execute("SELECT email FROM users WHERE user_id = %s", (created_by,))
            user_row = c.fetchone()
            user_email = user_row["email"] if user_row else None
            
        if not user_email:
            c.close()
            company_db.close()
            return build_response(False, "User email not found", 400)

        # Check for duplicates
        c.execute("SELECT id FROM workspaces WHERE workspace_name = %s", (workspace_name,))
        if c.fetchone():
            c.close()
            company_db.close()
            return build_response(False, f"Workspace name '{workspace_name}' already exists", 400)
            
        c.execute("INSERT INTO workspaces (workspace_name, created_by) VALUES (%s, %s)", (workspace_name, created_by))
        workspace_id = c.lastrowid
        
        # Auto-assign creator to the workspace
        c.execute("INSERT INTO workspace_users (workspace_id, user_email) VALUES (%s, %s)", (workspace_id, user_email))
        company_db.commit()
        
        c.close()
        company_db.close()
        
        return build_response(True, "Workspace created successfully", 200, {"workspace_id": workspace_id})
    except Exception as e:
        return build_response(False, f"Error creating workspace: {str(e)}", 500)


def list_workspaces_controller():
    try:
        data = request.get_json() or {}
        session_id = data.get("session_id")
        created_by = data.get("created_by")
        
        if not session_id or not created_by:
            return build_response(False, "session_id and created_by are required", 400)
            
        company_db_name = _get_company_db_name(session_id, created_by)
        if not company_db_name:
            return build_response(False, "Invalid session", 401)
            
        company_db = get_company_db(company_db_name)
        c = company_db.cursor(dictionary=True)
        
        c.execute("SELECT * FROM workspaces ORDER BY created_at DESC")
        workspaces = c.fetchall()
        workspaces = format_dates_in_rows(workspaces)
        
        c.close()
        company_db.close()
        
        return build_response(True, "Workspaces retrieved", 200, workspaces)
    except Exception as e:
        return build_response(False, f"Error fetching workspaces: {str(e)}", 500)


def assign_user_to_workspace_controller():
    try:
        data = request.get_json() or {}
        workspace_id = data.get("workspace_id")
        user_email = data.get("user_email")
        session_id = data.get("session_id")
        created_by = data.get("created_by")
        
        if not workspace_id or not user_email or not session_id or not created_by:
            return build_response(False, "workspace_id, user_email, session_id, and created_by are required", 400)
            
        company_db_name = _get_company_db_name(session_id, created_by)
        if not company_db_name:
            return build_response(False, "Invalid session", 401)
            
        company_db = get_company_db(company_db_name)
        c = company_db.cursor(dictionary=True)
        
        c.execute("SELECT * FROM workspaces WHERE id = %s", (workspace_id,))
        if not c.fetchone():
            c.close()
            company_db.close()
            return build_response(False, "Workspace not found", 404)
            
        c.execute("SELECT COUNT(*) as workspace_count FROM workspace_users WHERE user_email = %s", (user_email,))
        count = c.fetchone()["workspace_count"]
        
        if count >= 5:
            c.close()
            company_db.close()
            return build_response(False, "Maximum of 5 workspaces can be assigned to a user", 400)
            
        c.execute("SELECT id FROM workspace_users WHERE workspace_id = %s AND user_email = %s", (workspace_id, user_email))
        if c.fetchone():
            c.close()
            company_db.close()
            return build_response(False, "User is already assigned to this workspace", 400)
            
        c.execute("INSERT INTO workspace_users (workspace_id, user_email) VALUES (%s, %s)", (workspace_id, user_email))
        company_db.commit()
        
        c.close()
        company_db.close()
        
        return build_response(True, "User assigned to workspace successfully", 200)
    except Exception as e:
        return build_response(False, f"Error assigning user: {str(e)}", 500)


def get_assigned_users_controller():
    try:
        data = request.get_json() or {}
        workspace_id = data.get("workspace_id")
        session_id = data.get("session_id")
        created_by = data.get("created_by")
        
        if not workspace_id or not session_id or not created_by:
            return build_response(False, "workspace_id, session_id, and created_by are required", 400)
            
        company_db_name = _get_company_db_name(session_id, created_by)
        if not company_db_name:
            return build_response(False, "Invalid session", 401)
            
        company_db = get_company_db(company_db_name)
        c = company_db.cursor(dictionary=True)
        
        c.execute("SELECT id, user_email, assigned_at FROM workspace_users WHERE workspace_id = %s ORDER BY assigned_at DESC", (workspace_id,))
        users = c.fetchall()
        users = format_dates_in_rows(users)
        
        c.close()
        company_db.close()
        
        return build_response(True, "Assigned users retrieved", 200, users)
    except Exception as e:
        return build_response(False, f"Error fetching assigned users: {str(e)}", 500)


def get_user_workspaces_controller():
    try:
        data = request.get_json() or {}
        user_email = data.get("user_email")
        session_id = data.get("session_id")
        created_by = data.get("created_by")
        
        if not user_email or not session_id or not created_by:
            return build_response(False, "user_email, session_id, and created_by are required", 400)
            
        company_db_name = _get_company_db_name(session_id, created_by)
        if not company_db_name:
            return build_response(False, "Invalid session", 401)
            
        company_db = get_company_db(company_db_name)
        c = company_db.cursor(dictionary=True)
        
        c.execute('''
            SELECT w.id, w.workspace_name 
            FROM workspaces w
            JOIN workspace_users wu ON w.id = wu.workspace_id
            WHERE wu.user_email = %s
            ORDER BY w.created_at DESC
        ''', (user_email,))
        
        workspaces = c.fetchall()
        workspaces = format_dates_in_rows(workspaces)
        
        c.close()
        company_db.close()
        
        return build_response(True, "User workspaces retrieved", 200, workspaces)
    except Exception as e:
        return build_response(False, f"Error fetching user workspaces: {str(e)}", 500)

def get_all_users_for_workspace_controller():
    try:
        data = request.get_json() or {}
        session_id = data.get("session_id")
        created_by = data.get("created_by")
        
        if not session_id or not created_by:
            return build_response(False, "session_id and created_by are required", 400)
            
        master = get_master_db()
        mcur = master.cursor(dictionary=True)
        
        mcur.execute("SELECT company_db_name FROM user_company_sessions WHERE session_id = %s AND user_id = %s", (session_id, created_by))
        session = mcur.fetchone()
        if not session:
            mcur.close()
            master.close()
            return build_response(False, "Invalid session", 401)
            
        company_db_name = session["company_db_name"]
        
        mcur.execute("SELECT company_name FROM companies WHERE company_db_name = %s AND is_active=1 AND is_deleted=0", (company_db_name,))
        company_info = mcur.fetchone()
        mcur.close()
        master.close()
        
        if not company_info:
            return build_response(False, "Company not found or inactive", 404)
            
        company_name = company_info["company_name"]
        all_users = []
        
        try:
            company_db = get_company_db(company_db_name)
            ccur = company_db.cursor(dictionary=True)
            
            ccur.execute("SELECT wu.user_email, wu.workspace_id FROM workspace_users wu JOIN workspaces w ON wu.workspace_id = w.id")
            assignments = ccur.fetchall()
            user_workspaces = {}
            for row in assignments:
                email = row["user_email"]
                if email not in user_workspaces:
                    user_workspaces[email] = []
                user_workspaces[email].append(row["workspace_id"])
            
            ccur.execute("SELECT user_id, email, full_name FROM users WHERE is_deleted=0")
            users = ccur.fetchall()
            
            for u in users:
                u["company_name"] = company_name
                if not u.get("full_name"):
                    u["full_name"] = u["user_id"]
                if not u.get("email"):
                    u["email"] = u["user_id"]
                u["assigned_workspace_ids"] = user_workspaces.get(u["email"], [])
                all_users.append(u)
                
            ccur.close()
            company_db.close()
        except Exception as e:
            return build_response(False, f"Error accessing company database: {str(e)}", 500)
        
        all_users.sort(key=lambda x: (x.get("full_name") or "").lower())
        return build_response(True, "Users retrieved", 200, all_users)
    except Exception as e:
        return build_response(False, f"Error fetching users: {str(e)}", 500)
