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

def process_rag_chat(company_code: str, session_id: str, user_query: str, workspace_id: str = None):
    """
    Handles a user chat query by retrieving context from both ChromaDB and ArangoDB,
    then passing it to the LLM.
    """
    try:
        # Force workspace_id to string to match ChromaDB metadata
        if workspace_id is not None:
            workspace_id = str(workspace_id)
            
        # 1. Retrieve from Vector DB (ChromaDB)
        vector_results = query_chroma(company_code, user_query, n_results=5, workspace_id=workspace_id)
        
        vector_context = []
        if vector_results and "documents" in vector_results and vector_results["documents"]:
            vector_context = vector_results["documents"][0]
            
        vector_text = "\n".join(vector_context)
        
        # 2. Extract potential entities from user_query to search Graph DB
        # A simple heuristic: split query into words or ask LLM for keywords.
        # For speed, we just take significant words > 4 chars.
        search_terms = [w.strip('?.,') for w in user_query.split() if len(w) > 4]
        
        graph_results = query_graph_context(company_code, search_terms, workspace_id=workspace_id)
        
        graph_text = ""
        if graph_results:
            graph_text = "\n".join([f"{r['source']} --[{r['relationship']}]--> {r['target']}" for r in graph_results])
            
        # 3. Retrieve from MySQL normalized_knowledge
        db_text = ""
        mysql_chunks = 0
        db = None
        cursor = None
        try:
            company_db_name = _get_company_db_name(company_code)
            if company_db_name:
                db = get_company_db(company_db_name)
                if db:
                    cursor = db.cursor(dictionary=True)
                    # simple full text like search using search terms
                    if search_terms:
                        conditions = " OR ".join(["content LIKE %s" for _ in search_terms])
                        params = [f"%{term}%" for term in search_terms]
                        
                        if workspace_id:
                            conditions = f"({conditions}) AND workspace_id = %s"
                            params.append(workspace_id)
                            
                        cursor.execute(f"SELECT content FROM normalized_knowledge WHERE {conditions} LIMIT 5", params)
                        db_results = cursor.fetchall()
                        mysql_chunks = len(db_results)
                        db_text = "\n".join([r['content'] for r in db_results])
        except Exception as e:
            print(f"MySQL RAG Error: {e}")
        finally:
            if cursor is not None:
                try:
                    cursor.close()
                except Exception:
                    pass
            if db is not None:
                try:
                    db.close()
                except Exception:
                    pass

        # 4. Build Prompt for LLM
        prompt = f"""
        You are an intelligent data assistant answering user questions based on the provided context.
        
        --- VECTOR CONTEXT (Semantic Chunks) ---
        {vector_text if vector_text else "No specific vector context found."}
        
        --- DATABASE CONTEXT (Normalized Knowledge) ---
        {db_text if db_text else "No specific database context found."}
        
        --- GRAPH CONTEXT (Entity Relationships) ---
        {graph_text if graph_text else "No specific graph relationships found."}
        
        ---
        User Question: {user_query}
        
        Answer the question thoroughly and accurately using ONLY the context provided above. 
        If the answer is not in the context, say "I don't have enough data to answer that."
        """
        
        # 4. Get LLM Answer
        ai_answer = call_llm(prompt)
        
        # 5. Build final response
        return build_response(True, "RAG Chat Successful", 200, {
            "ai_answer": ai_answer,
            "sources": {
                "vector_chunks": len(vector_context),
                "graph_edges": len(graph_results),
                "mysql_chunks": mysql_chunks
            }
        })
        
    except Exception as e:
        print(f"[RAG Chat Error] {e}")
        return build_response(False, f"RAG Engine Error: {e}", 500)
