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
        workspace_id = data.get("workspace_id")
        created_by = data.get("created_by")
        
        if not all([company_code, session_id, query]):
            return build_response(False, "Missing required fields", 400)
        success, message = ingest_web_search(company_code, session_id, query, workspace_id=workspace_id, ingest_to_vector_graph=True, created_by=created_by)
        
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
        
        scope = data.get("scope", "all")
        
        if not all([company_code, session_id, user_query]):
            return build_response(False, "Missing required fields", 400)
            
        return process_rag_chat(company_code, session_id, user_query, workspace_id, scope=scope)
        
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
            CREATE TABLE IF NOT EXISTS rag_chat_history (
                id INT AUTO_INCREMENT PRIMARY KEY,
                session_id VARCHAR(100),
                user_id VARCHAR(100),
                workspace_id INT,
                user_query TEXT,
                ai_response TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
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
        cursor.execute(
            """
            CREATE TABLE IF NOT EXISTS rag_chat_history (
                id INT AUTO_INCREMENT PRIMARY KEY,
                session_id VARCHAR(100),
                user_id VARCHAR(100),
                workspace_id INT,
                user_query TEXT,
                ai_response TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
            """
        )
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

from flask import g
import os
from helper.helperFunctions import get_upload_folder

def rag_ingest_selected_controller():
    """
    POST /rag/ingest/selected
    Body: {"csv_files": [...], "web_searches": [...], "session_id": "...", "workspace_id": "...", "created_by": "..."}
    """
    try:
        data = request.get_json() or {}
        session_id = data.get("session_id")
        workspace_id = data.get("workspace_id")
        created_by = data.get("created_by")
        csv_files = data.get("csv_files", [])
        web_searches = data.get("web_searches", [])

        if not session_id or not created_by:
            return build_response(False, "Missing session_id or created_by", 400)

        if not hasattr(g, "company_db"):
            return build_response(False, "Invalid session", 401)

        company_db = g.company_db
        company_code = company_db.database

        from helper.rag_ingestion import ingest_uploaded_csv, process_and_store_text

        # 1. Process CSVs
        upload_folder = get_upload_folder()
        for fname in csv_files:
            file_path = os.path.join(upload_folder, fname)
            if os.path.exists(file_path):
                # Pass ingest_to_vector_graph=True
                ingest_uploaded_csv(company_code, session_id, file_path, workspace_id, ingest_to_vector_graph=True)

        # 2. Process Web Searches
        # To avoid duplicated live search, we read the content from normalized_knowledge
        # and then push to VectorDB/GraphDB via process_and_store_text.
        cursor = company_db.cursor(dictionary=True)
        for sname in web_searches:
            cursor.execute("SELECT content FROM normalized_knowledge WHERE source_type = 'web_search' AND source_name = %s", (sname,))
            rows = cursor.fetchall()
            if rows:
                # Combine chunks back to a single text to process, or process them as a single block
                combined_text = "\n".join([r["content"] for r in rows if r["content"]])
                if combined_text:
                    process_and_store_text(company_code, session_id, combined_text, sname, workspace_id, ingest_to_vector_graph=True)
        cursor.close()

        return build_response(True, "Selected sources ingested for RAG successfully.", 200)
    except Exception as e:
        return build_response(False, f"Ingest Selected Error: {str(e)}", 500)
