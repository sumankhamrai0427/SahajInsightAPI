import json
from flask import request, g
from helper.helperFunctions import build_response
from model.llm_client import call_llm
from controller.sql_ai_executor import chat_endpoint_controller
from controller.rag_controller import rag_chat_controller

def classify_query_intent(user_query):
    """
    Uses an LLM to quickly classify the user intent as 'SQL' or 'RAG'.
    """
    prompt = f"""
    You are an intelligent router for an AI agent.
    Your job is to classify the following user query into exactly one of two categories: 'SQL' or 'RAG'.

    - Respond with 'SQL' if the query is asking to retrieve, aggregate, or filter structured data from a database (e.g., "Show me all employees", "What is the total sales?", "List customers who bought X").
    - Respond with 'RAG' if the query is asking a general knowledge question, asking to summarize documents, deep search unstructured text, or asking for policies (e.g., "What is our leave policy?", "Summarize the report", "How does X work?").

    User Query: "{user_query}"

    Respond with ONLY 'SQL' or 'RAG'.
    """
    try:
        response = call_llm(prompt).strip().upper()
        if 'SQL' in response:
            return 'SQL'
        elif 'RAG' in response:
            return 'RAG'
    except Exception as e:
        print(f"Error classifying intent: {e}")
    
    # Default fallback to RAG if classification fails
    return 'RAG'

def unified_chat_controller():
    """
    POST /chat/unified
    Body: {"company_code": "...", "session_id": "...", "user_query": "...", "workspace_id": "..."}
    """
    try:
        data = request.get_json() or {}
        user_query = data.get("user_query")
        session_id = data.get("session_id")

        if not all([session_id, user_query]):
            return build_response(False, "Missing required fields", 400)

        # 1. Classify the intent
        chat_type = classify_query_intent(user_query)

        # 2. Route the request
        if chat_type == 'SQL':
            # chat_endpoint_controller reads directly from request.get_json() and uses g.company_db
            response_tuple = chat_endpoint_controller()
            
            # response_tuple is typically what build_response returns, which is a flask Response object
            # We need to inject 'chat_type' into the JSON response
            if hasattr(response_tuple, 'get_json'):
                resp_json = response_tuple.get_json()
                if resp_json and isinstance(resp_json, dict):
                    resp_json['chat_type'] = 'sql'
                    response_tuple.set_data(json.dumps(resp_json))
            
            return response_tuple
            
        else:
            # RAG
            response_tuple = rag_chat_controller()
            
            if hasattr(response_tuple, 'get_json'):
                resp_json = response_tuple.get_json()
                if resp_json and isinstance(resp_json, dict):
                    resp_json['chat_type'] = 'rag'
                    response_tuple.set_data(json.dumps(resp_json))
            
            return response_tuple

    except Exception as e:
        return build_response(False, f"Unified Chat Error: {str(e)}", 500)
