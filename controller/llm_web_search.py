import json
from flask import request
from helper.helperFunctions import build_response
from model.llm_client import call_llm
from database.dbConnection import get_master_db
import threading

def llm_web_search_controller():
    try:
        data = request.get_json() or {}
        user_query = data.get("user_query")
        
        if not user_query:
            return build_response(False, "Missing user_query", 400)
            
        # Fetch live web data first
        from helper.web_search import live_web_search
        live_data = live_web_search(user_query)

        # Structure prompt for search response
        prompt = f"""
You are a web search assistant. Research, synthesize, and summarize details for the query below.
Query: "{user_query}"

Here is the latest data retrieved from the web:
{live_data}

Provide a clean, informative, and detailed response based on the latest context provided above.
"""
        ai_response = call_llm(prompt)
        
        session_id = data.get("session_id")
        created_by = data.get("created_by")
        workspace_id = data.get("workspace_id")
        
        if session_id and created_by:
            db = get_master_db()
            cursor = db.cursor(dictionary=True)
            cursor.execute("SELECT company_db_name FROM user_company_sessions WHERE session_id = %s", (session_id,))
            row = cursor.fetchone()
            company_code = row["company_db_name"] if row else None
            cursor.close()
            db.close()
            
            if company_code:
                from helper.rag_ingestion import ingest_web_search
                def background_ingest():
                    try:
                        # Pass live_data as ai_response so it stores the raw web snippets in DB
                        ingest_web_search(company_code, session_id, user_query, live_data, workspace_id, created_by=created_by)
                    except Exception as e:
                        print("Background Web Search Ingest Error:", e)
                threading.Thread(target=background_ingest).start()
        
        return build_response(True, "Search processed", 200, {
            "ai_response": ai_response
        })
        
    except Exception as e:
        return build_response(False, f"Web Search Error: {str(e)}", 500)
