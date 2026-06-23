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

def suggest_questions_controller():
    import json
    import re
    try:
        data = request.get_json() or {}
        session_id = data.get("session_id")
        created_by = data.get("created_by")
        workspace_id = data.get("workspace_id")
        
        if not session_id or not created_by:
            return build_response(False, "session_id and created_by are required", 400)
            
        company_db_name = _get_company_db_name(session_id, created_by)
        if not company_db_name:
            return build_response(False, "Invalid session", 401)
            
        company_db = get_company_db(company_db_name)
        c = company_db.cursor(dictionary=True)
        
        # 1. Fetch uploaded files metadata in this workspace with fallback
        files = []
        if workspace_id and str(workspace_id).lower() != 'all':
            c.execute(
                """
                SELECT table_name, file_name, insights
                FROM uploaded_files
                WHERE workspace_id = %s AND data_insert_status = 'done'
                """,
                (workspace_id,)
            )
            files = c.fetchall()
            
        if not files:
            # Fallback to 'all' or no workspace_id filter
            c.execute(
                """
                SELECT table_name, file_name, insights
                FROM uploaded_files
                WHERE (workspace_id = 'all' OR workspace_id IS NULL) AND data_insert_status = 'done'
                """
            )
            files = c.fetchall()
            
        if not files:
            # Fallback to any completed file in the database
            c.execute(
                """
                SELECT table_name, file_name, insights
                FROM uploaded_files
                WHERE data_insert_status = 'done'
                LIMIT 5
                """
            )
            files = c.fetchall()
        
        # 2. For each table, fetch the column schemas
        tables_metadata = []
        for f in files:
            table_name = f.get("table_name")
            file_name = f.get("file_name")
            insights = f.get("insights")
            
            if not table_name:
                continue
                
            c.execute(
                """
                SELECT COLUMN_NAME, DATA_TYPE
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s
                ORDER BY ORDINAL_POSITION
                """,
                (table_name,)
            )
            columns = c.fetchall()
            col_list = [f"{col['COLUMN_NAME']} ({col['DATA_TYPE']})" for col in columns]
            
            tables_metadata.append({
                "table_name": table_name,
                "file_name": file_name,
                "columns": col_list,
                "insights": insights
            })
            
        c.close()
        company_db.close()
        
        # 3. Call LLM to generate questions
        if not tables_metadata:
            # Fallback if no tables exist in workspace yet
            default_questions = [
                "What insights can you help me extract from my uploaded business databases?",
                "Can you identify trends and anomalies in my workspace data?",
                "How can I join and query multiple files in my workspace?",
                "What are the top recommended business actions based on my datasets?"
            ]
            return build_response(True, "Default questions generated", 200, default_questions)
            
        schema_text = ""
        for t in tables_metadata:
            schema_text += f"Table: {t['table_name']} (Original file: {t['file_name']})\n"
            schema_text += f"Columns: {', '.join(t['columns'])}\n"
            if t['insights']:
                schema_text += f"Insights: {t['insights'][:300]}\n"
            schema_text += "\n"
            
        prompt = f"""
        You are an AI business analyst. Based on the following database tables in the user's workspace, generate exactly 4 distinct, analytical, and highly business-relevant sample questions that a user could ask to analyze this data.
        
        Workspace Tables:
        {schema_text}
        
        Rules:
        1. The questions should be clear, professional, and natural.
        2. Refer to actual table names or column names where appropriate.
        3. Do NOT make up columns or tables that do not exist.
        4. Return ONLY a valid JSON array of exactly 4 strings.
        5. Do NOT wrap the JSON in markdown code blocks like ```json ... ```. Just return the raw JSON array string.
        
        Example Output:
        ["What is the total sales amount by product category?", "How does client retention correlate with purchase frequency?", "Which region shows the highest anomaly in shipping delay?", "What are the top 5 product categories by margin?"]
        """
        
        from model.llm_client import call_llm
        llm_response = call_llm(prompt)
        
        # Parse JSON from response
        try:
            clean_resp = llm_response.strip()
            if clean_resp.startswith("```"):
                clean_resp = re.sub(r"^```(?:json)?\n", "", clean_resp)
                clean_resp = re.sub(r"\n```$", "", clean_resp)
                clean_resp = clean_resp.strip()
                
            array_match = re.search(r"\[\s*\".*\"\s*\]", clean_resp, re.DOTALL)
            if array_match:
                clean_resp = array_match.group(0)
                
            questions = json.loads(clean_resp)
            if isinstance(questions, list) and len(questions) >= 4:
                return build_response(True, "Questions generated successfully", 200, questions[:4])
        except Exception as json_err:
            print(f"Failed to parse LLM questions json: {json_err}, raw response: {llm_response}")
            
        # Fallback
        default_questions = [
            f"Can you provide a summary analysis of the tables: {', '.join([t['table_name'] for t in tables_metadata])}?",
            "What are the key insights and anomalies in our uploaded datasets?",
            "How do the main columns in our tables correlate with performance?",
            "What are the top recommended business actions based on our data?"
        ]
        return build_response(True, "Fallback questions generated", 200, default_questions)
        
    except Exception as e:
        return build_response(False, f"Error suggesting questions: {str(e)}", 500)
