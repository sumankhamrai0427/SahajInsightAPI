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
                    # Query using search terms with flexible OR LIKE matching
                    db_results = []
                    if search_terms:
                        # Join with OR to match any keyword, making the search flexible
                        conditions = " OR ".join(["content LIKE %s" for _ in search_terms])
                        params = [f"%{term}%" for term in search_terms]
                        
                        if workspace_id and str(workspace_id).lower() != "all":
                            # Try with workspace filter first
                            conditions_ws = f"({conditions}) AND (workspace_id = %s OR workspace_id = 'all' OR workspace_id IS NULL)"
                            params_ws = params + [workspace_id]
                            cursor.execute(f"SELECT content FROM normalized_knowledge WHERE {conditions_ws} LIMIT 25", params_ws)
                            db_results = cursor.fetchall()
                            
                        if not db_results:
                            # Fallback: query across all workspace data for the company
                            cursor.execute(f"SELECT content FROM normalized_knowledge WHERE {conditions} LIMIT 25", params)
                            db_results = cursor.fetchall()
                            
                    # Robust Fallback: if no search terms match, or no results found, fetch recent/any records from this workspace or globally
                    if not db_results:
                        if workspace_id and str(workspace_id).lower() != "all":
                            cursor.execute(
                                """
                                SELECT content FROM normalized_knowledge 
                                WHERE workspace_id = %s OR workspace_id = 'all' OR workspace_id IS NULL 
                                LIMIT 25
                                """,
                                (workspace_id,)
                            )
                            db_results = cursor.fetchall()
                        if not db_results:
                            cursor.execute("SELECT content FROM normalized_knowledge LIMIT 25")
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
        You are an intelligent data assistant answering user questions. You must use the provided context to identify specific entities, metrics, or records (e.g., customer names, car models, purchased items, etc.).
        
        If the context provides the specific records but lacks general information/explanation about them (e.g., whether a car model is suitable for city driving, general use cases, expert opinions, etc.), you are encouraged to supplement the answer using your own general knowledge.
        
        --- VECTOR CONTEXT (Semantic Chunks) ---
        {vector_text if vector_text else "No specific vector context found."}
        
        --- DATABASE CONTEXT (Normalized Knowledge) ---
        {db_text if db_text else "No specific database context found."}
        
        --- GRAPH CONTEXT (Entity Relationships) ---
        {graph_text if graph_text else "No specific graph relationships found."}
        
        ---
        User Question: {user_query}
        
        Answer the user question thoroughly. Highlight which parts of the information came from the database context (like customer names, purchased car models, etc.) and which parts are based on general expert knowledge (like suitability, use cases, etc.).
        
        If the database/vector/graph context is completely empty or contains absolutely no data matching the overall domain of the query (e.g. no customers, cars, or order records exist in the context tables), only then say "I don't have enough data to answer that." Otherwise, synthesize the available records with your expert general knowledge to provide a comprehensive response.
        """
        
        # 4. Get LLM Answer
        ai_answer = call_llm(prompt)
        
        # Prepend source URLs/references to the RAG Chat response
        import re
        unique_sources = []
        
        # 1. Parse web search URLs from the text content
        all_context = "\n".join(vector_context) + "\n" + db_text
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
            if vector_context or db_text or graph_text:
                source_header = "Source: Database / Uploaded Files\n\n---\n\n"
            else:
                source_header = "Source: AI General Knowledge\n\n---\n\n"
                
        ai_answer = source_header + ai_answer
        
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
