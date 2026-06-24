from database.vector_db import query_chroma
from database.graph_db import query_graph_context
from model.llm_client import call_llm
from helper.helperFunctions import build_response
from database.dbConnection import get_company_db, get_master_db
import json

def _get_company_db_name(company_code):
    master = None
    cur = None
    try:
        master = get_master_db()
        cur = master.cursor(dictionary=True)
        cur.execute("SELECT company_db_name FROM companies WHERE company_code = %s", (company_code,))
        row = cur.fetchone()
        return row["company_db_name"] if row else None
    finally:
        if cur is not None:
            try:
                cur.close()
            except Exception:
                pass
        if master is not None:
            try:
                master.close()
            except Exception:
                pass

def process_rag_chat(company_code: str, session_id: str, user_query: str, workspace_id: str = None, scope: str = "all"):
    """
    Handles a user chat query by retrieving context from both ChromaDB and ArangoDB,
    then passing it to the LLM.
    """
    try:
        # Force workspace_id to string to match ChromaDB metadata
        if workspace_id is not None:
            workspace_id = str(workspace_id)
            
        # Determine whether to search globally/workspace-wide or strictly session-wide
        active_session_id = session_id if scope == "selected" else None
            
        # 1. Retrieve from Vector DB (ChromaDB)
        vector_results = query_chroma(company_code, user_query, n_results=12, workspace_id=workspace_id, session_id=active_session_id)
        
        vector_context = []
        if vector_results and "documents" in vector_results and vector_results["documents"]:
            vector_context = vector_results["documents"][0]
            
        vector_text = "\n".join(vector_context)
        
        # 2. Build Prompt for LLM
        prompt = f"""
        You are a strict data assistant. You must answer the user's question ONLY using the provided context (Vector context). 
        
        Strict Guidelines:
        1. If the answer to the user's question cannot be found or reasonably inferred from the provided context, you MUST respond with exactly: "I don't have this data."
        2. Do NOT use your general knowledge to answer questions that are not related to or supported by the provided data (for example, general questions like "what is AI", "who is the president", or general coding/math queries).
        3. Do NOT make up, assume, or extrapolate any information not present in the context.
        4. Focus strictly on the entities, metrics, and records present in the context.
        
        --- VECTOR CONTEXT (Semantic Chunks) ---
        {vector_text if vector_text else "No specific context found."}
        
        ---
        User Question: {user_query}
        
        Answer the user question strictly using the context above. If you cannot answer it using only the provided context, respond with "I don't have this data."
        """
        
        # 3. Get LLM Answer
        ai_answer = call_llm(prompt)
        
        # Check if the LLM output indicates lack of data
        clean_ai_answer = ai_answer.strip().strip('"').strip("'").strip().lower()
        is_no_data = (
            "don't have this data" in clean_ai_answer or 
            "don't have enough data" in clean_ai_answer or 
            "do not have this data" in clean_ai_answer or
            "i don't have that data" in clean_ai_answer or
            clean_ai_answer == "i don't have this data"
        )
        
        if is_no_data:
            ai_answer = "I don't have this data."
        else:
            # Prepend source URLs/references to the RAG Chat response
            import re
            unique_sources = []
            
            # 1. Parse web search URLs from the vector context
            all_context = "\n".join(vector_context)
            web_urls = re.findall(r'---\s+Source:\s*(https?://\S+)', all_context)
            old_web_urls = re.findall(r'(?:^|\n)Source:\s*(https?://\S+)', all_context)
            web_urls.extend(old_web_urls)
            
            for url in web_urls:
                if url not in unique_sources:
                    unique_sources.append(url)
                    
            # 2. Extract database table/file sources from metadata
            db_sources = []
            if vector_results and "metadatas" in vector_results and vector_results["metadatas"]:
                for meta in vector_results["metadatas"][0]:
                    if meta and isinstance(meta, dict):
                        src = meta.get("source")
                        if src:
                            if src.startswith("web_search_"):
                                continue
                            table_repr = f"Database Table: {src.replace('.csv', '')}"
                            if table_repr not in db_sources:
                                db_sources.append(table_repr)
                                
            final_sources = unique_sources + db_sources
            
            if final_sources:
                source_header = "Sources:\n" + "\n".join(f"- {s}" for s in final_sources) + "\n\n---\n\n"
            else:
                if vector_context:
                    source_header = "Source: Database / Uploaded Files\n\n---\n\n"
                else:
                    source_header = "Source: AI General Knowledge\n\n---\n\n"
                    
            ai_answer = source_header + ai_answer
        
        # 4. Build final response
        return build_response(True, "RAG Chat Successful", 200, {
            "ai_answer": ai_answer,
            "sources": {
                "vector_chunks": len(vector_context),
                "graph_edges": 0,
                "mysql_chunks": 0
            }
        })
        
    except Exception as e:
        print(f"[RAG Chat Error] {e}")
        return build_response(False, f"RAG Engine Error: {e}", 500)
