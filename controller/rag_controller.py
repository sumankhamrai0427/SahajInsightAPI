from flask import request
from helper.helperFunctions import build_response
from helper.rag_ingestion import ingest_web_search, ingest_uploaded_csv
from helper.rag_engine import process_rag_chat
import os
from werkzeug.utils import secure_filename
from helper.helperFunctions import get_upload_folder

def rag_ingest_web_search_controller():
    """
    POST /rag/ingest/web_search
    Body: {"company_code": "...", "session_id": "...", "query": "..."}
    """
    try:
        data = request.get_json() or {}
        company_code = data.get("company_code")
        session_id = data.get("session_id")
        query = data.get("query")
        
        if not all([company_code, session_id, query]):
            return build_response(False, "Missing required fields", 400)
            
        success, message = ingest_web_search(company_code, session_id, query)
        
        if success:
            return build_response(True, message, 200)
        else:
            return build_response(False, message, 500)
            
    except Exception as e:
        return build_response(False, f"Ingestion Error: {str(e)}", 500)

def rag_ingest_csv_controller():
    """
    POST /rag/ingest/csv
    Form Data: file, company_code, session_id
    """
    try:
        if 'file' not in request.files:
            return build_response(False, "No file provided", 400)
            
        file = request.files['file']
        company_code = request.form.get("company_code")
        session_id = request.form.get("session_id")
        
        if not all([company_code, session_id]):
            return build_response(False, "Missing company_code or session_id", 400)
            
        if file.filename == '':
            return build_response(False, "Empty filename", 400)
            
        filename = secure_filename(file.filename)
        upload_folder = get_upload_folder()
        os.makedirs(upload_folder, exist_ok=True)
        file_path = os.path.join(upload_folder, filename)
        
        file.save(file_path)
        
        success, message = ingest_uploaded_csv(company_code, session_id, file_path)
        
        if success:
            return build_response(True, message, 200)
        else:
            return build_response(False, message, 500)
            
    except Exception as e:
        return build_response(False, f"CSV Ingestion Error: {str(e)}", 500)

def rag_chat_controller():
    """
    POST /rag/chat
    Body: {"company_code": "...", "session_id": "...", "user_query": "...", "workspace_id": "..."}
    """
    try:
        data = request.get_json() or {}
        company_code = data.get("company_code")
        session_id = data.get("session_id")
        user_query = data.get("user_query")
        workspace_id = data.get("workspace_id")
        
        if not all([company_code, session_id, user_query]):
            return build_response(False, "Missing required fields", 400)
            
        return process_rag_chat(company_code, session_id, user_query, workspace_id)
        
    except Exception as e:
        return build_response(False, f"Chat Error: {str(e)}", 500)

from database.dbConnection import get_company_db, get_master_db

def _get_company_db_name(company_code):
    master = get_master_db()
    cur = master.cursor(dictionary=True)
    cur.execute("SELECT company_db_name FROM companies WHERE company_code = %s", (company_code,))
    row = cur.fetchone()
    cur.close()
    master.close()
    return row["company_db_name"] if row else None

def save_rag_chat_controller():
    """
    POST /rag/chat/save
    Body: {"company_code": "...", "session_id": "...", "user_id": "...", "workspace_id": 1, "user_query": "...", "ai_response": "..."}
    """
    try:
        data = request.get_json() or {}
        company_code = data.get("company_code")
        session_id = data.get("session_id")
        user_id = data.get("user_id")
        workspace_id = data.get("workspace_id")
        user_query = data.get("user_query")
        ai_response = data.get("ai_response")

        if not all([company_code, session_id, user_id, user_query, ai_response]):
            return build_response(False, "Missing required fields", 400)

        company_db_name = _get_company_db_name(company_code)
        if not company_db_name:
            return build_response(False, "Invalid company code", 400)

        db = get_company_db(company_db_name)
        if not db:
            return build_response(False, "Database connection failed", 500)

        cursor = db.cursor()
        cursor.execute(
            """
            INSERT INTO rag_chat_history (session_id, user_id, workspace_id, user_query, ai_response)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (session_id, user_id, workspace_id, user_query, ai_response)
        )
        db.commit()
        cursor.close()
        db.close()

        return build_response(True, "RAG chat saved successfully", 200)
    except Exception as e:
        return build_response(False, f"Save RAG Chat Error: {str(e)}", 500)

def get_rag_chat_history_controller():
    """
    POST /rag/chat/history
    Body: {"company_code": "...", "user_id": "...", "workspace_id": 1}
    """
    try:
        data = request.get_json() or {}
        company_code = data.get("company_code")
        user_id = data.get("user_id")
        workspace_id = data.get("workspace_id")

        if not all([company_code, user_id]):
            return build_response(False, "Missing required fields", 400)

        company_db_name = _get_company_db_name(company_code)
        if not company_db_name:
            return build_response(False, "Invalid company code", 400)

        db = get_company_db(company_db_name)
        if not db:
            return build_response(False, "Database connection failed", 500)

        cursor = db.cursor(dictionary=True)
        if workspace_id:
            cursor.execute(
                """
                SELECT id, session_id, user_id, workspace_id, user_query, ai_response, created_at
                FROM rag_chat_history
                WHERE user_id = %s AND workspace_id = %s
                ORDER BY created_at ASC
                """,
                (user_id, workspace_id)
            )
        else:
            cursor.execute(
                """
                SELECT id, session_id, user_id, workspace_id, user_query, ai_response, created_at
                FROM rag_chat_history
                WHERE user_id = %s AND workspace_id IS NULL
                ORDER BY created_at ASC
                """,
                (user_id,)
            )

        history = cursor.fetchall()
        
        # Format dates
        for h in history:
            if h.get('created_at'):
                h['created_at'] = h['created_at'].strftime('%Y-%m-%d %H:%M:%S')

        cursor.close()
        db.close()

        return build_response(True, "RAG chat history fetched", 200, {"history": history})
    except Exception as e:
        return build_response(False, f"Get RAG Chat History Error: {str(e)}", 500)
