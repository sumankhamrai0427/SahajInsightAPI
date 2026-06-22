import pandas as pd
from langchain_text_splitters import RecursiveCharacterTextSplitter
from database.vector_db import add_chunks_to_chroma
from database.graph_db import add_graph_data
from helper.web_search import live_web_search
from model.llm_client import call_llm
from database.dbConnection import get_company_db
import hashlib
import json
import re

# Text Splitter for Vector DB
text_splitter = RecursiveCharacterTextSplitter(
    chunk_size=500,
    chunk_overlap=50,
    length_function=len,
    is_separator_regex=False,
)

def extract_entities_with_llm(text_chunk: str):
    """
    Uses the LLM to extract nodes (entities) and edges (relationships) from text.
    """
    prompt = f"""
    You are a data architect extracting graph data.
    Extract the main entities and their relationships from the text below.
    
    Text: {text_chunk}
    
    Return ONLY a JSON object exactly matching this structure (no markdown, no explanations):
    {{
      "nodes": [
        {{"_key": "unique_id_1", "type": "Category", "name": "Value"}},
        {{"_key": "unique_id_2", "type": "Category", "name": "Value"}}
      ],
      "edges": [
        {{"_from": "unique_id_1", "_to": "unique_id_2", "type": "RELATIONSHIP_NAME"}}
      ]
    }}
    Make _key lowercase alphanumeric.
    """
    
    try:
        response = call_llm(prompt)
        # Find the first { and last } to extract JSON
        start_idx = response.find("{")
        end_idx = response.rfind("}")
        if start_idx != -1 and end_idx != -1 and start_idx < end_idx:
            clean_json = response[start_idx:end_idx+1]
        else:
            clean_json = "{}"
            
        data = json.loads(clean_json)
        return data.get("nodes", []), data.get("edges", [])
    except Exception as e:
        print(f"[LLM Extraction Error] {e}")
        return [], []

def process_and_store_data(company_code: str, session_id: str, df: pd.DataFrame, source_name: str, workspace_id: str = None, ingest_to_vector_graph: bool = False):
    """
    Core pipeline that pushes dataframe content to ChromaDB and ArangoDB (conditionally) and MySQL.
    """
    if df.empty:
        return False, "Dataframe is empty"
        
    all_chunks = []
    metadatas = []
    ids = []
    
    all_nodes = []
    all_edges = []
    
    # Process each row into a text chunk
    for idx, row in df.iterrows():
        row_dict = row.dropna().to_dict()
        if not row_dict:
            continue
            
        # Create text representation of the row
        text_content = ", ".join([f"{k}: {v}" for k, v in row_dict.items()])
        
        # Split into smaller chunks if necessary (though usually a row is small enough)
        chunks = text_splitter.split_text(text_content)
        
        for i, chunk in enumerate(chunks):
            chunk_id = hashlib.md5(f"{session_id}_{source_name}_{idx}_{i}".encode()).hexdigest()
            all_chunks.append(chunk)
            meta = {
                "source": source_name,
                "session_id": session_id,
                "row_index": idx
            }
            if workspace_id is not None:
                meta["workspace_id"] = str(workspace_id)
            metadatas.append(meta)
            ids.append(chunk_id)
            
            # Extract graph data ONLY for web search (too slow/expensive for full CSVs)
            if "web_search" in source_name:
                nodes, edges = extract_entities_with_llm(chunk)
                for n in nodes: n["workspace_id"] = workspace_id
                for e in edges: e["workspace_id"] = workspace_id
                all_nodes.extend(nodes)
                all_edges.extend(edges)

    # 1. Store in ChromaDB
    if ingest_to_vector_graph:
        try:
            add_chunks_to_chroma(company_code, all_chunks, metadatas, ids)
        except Exception as e:
            return False, f"ChromaDB Error: {e}"

        # 2. Store in ArangoDB
        try:
            add_graph_data(company_code, all_nodes, all_edges)
        except Exception as e:
            print(f"ArangoDB Error: {e}")

    # 3. Store in normalized_knowledge (MySQL)
    db = None
    cursor = None
    try:
        db = get_company_db(company_code)
        if db:
            cursor = db.cursor()
            source_type = "web_search" if "web_search" in source_name else "csv"
            
            # Fix empty workspace_id
            safe_workspace_id = None if not workspace_id or str(workspace_id).strip() == "" else workspace_id
            
            insert_sql = """
                INSERT INTO normalized_knowledge 
                (company_code, session_id, workspace_id, source_type, source_name, content, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """
            
            # Prepare data
            mysql_data = []
            for i, chunk in enumerate(all_chunks):
                mysql_data.append((
                    company_code,
                    session_id,
                    safe_workspace_id,
                    source_type,
                    source_name,
                    chunk,
                    json.dumps(metadatas[i])
                ))
                
            cursor.executemany(insert_sql, mysql_data)
            db.commit()
    except Exception as e:
        print(f"MySQL Normalized Knowledge Error: {e}")
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

    return True, f"Stored {len(all_chunks)} chunks in Vector DB, Graph DB, and MySQL."

def process_and_store_text(company_code: str, session_id: str, text: str, source_name: str, workspace_id: str = None, ingest_to_vector_graph: bool = False, created_by: str = None):
    """
    Direct pipeline for unstructured text (like web search responses) to avoid CSV conversion failures.
    """
    if not text or not text.strip():
        return False, "Text is empty"
        
    all_chunks = text_splitter.split_text(text)
    metadatas = []
    ids = []
    
    all_nodes = []
    all_edges = []
    
    for i, chunk in enumerate(all_chunks):
        chunk_id = hashlib.md5(f"{session_id}_{source_name}_{i}".encode()).hexdigest()
        meta = {
            "source": source_name,
            "session_id": session_id,
            "chunk_index": i
        }
        if workspace_id is not None:
            meta["workspace_id"] = str(workspace_id)
        metadatas.append(meta)
        ids.append(chunk_id)
        
        # Extract graph data for web search
        nodes, edges = extract_entities_with_llm(chunk)
        for n in nodes: n["workspace_id"] = workspace_id
        for e in edges: e["workspace_id"] = workspace_id
        all_nodes.extend(nodes)
        all_edges.extend(edges)

    # 1. Store in ChromaDB
    if ingest_to_vector_graph:
        try:
            add_chunks_to_chroma(company_code, all_chunks, metadatas, ids)
        except Exception as e:
            return False, f"ChromaDB Error: {e}"

        # 2. Store in ArangoDB
        try:
            if all_nodes or all_edges:
                add_graph_data(company_code, all_nodes, all_edges)
        except Exception as e:
            print(f"ArangoDB Error: {e}")

    # 3. Store in normalized_knowledge (MySQL)
    db = None
    cursor = None
    try:
        db = get_company_db(company_code)
        if db:
            cursor = db.cursor()
            source_type = "web_search"
            
            # Fix empty workspace_id
            safe_workspace_id = None if not workspace_id or str(workspace_id).strip() == "" else workspace_id
            
            insert_sql = """
                INSERT INTO normalized_knowledge 
                (company_code, session_id, workspace_id, source_type, source_name, content, metadata)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
            """
            
            mysql_data = []
            for i, chunk in enumerate(all_chunks):
                mysql_data.append((
                    company_code,
                    session_id,
                    safe_workspace_id,
                    source_type,
                    source_name,
                    chunk,
                    json.dumps(metadatas[i])
                ))
                
            cursor.executemany(insert_sql, mysql_data)
            db.commit()

            # Insert into uploaded_files
            try:
                uf_sql = """
                    INSERT INTO uploaded_files 
                    (session_id, created_by, workspace_id, file_name, table_name, file_size_mb, file_type, 
                     total_columns, last_inserted_rows, table_extraction_status, column_extraction_status, 
                     data_insights_status, data_insert_status, insights)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """
                uf_values = (
                    session_id,
                    created_by or 'system',
                    safe_workspace_id,
                    source_name,
                    'Web Search Data',
                    '0 MB',
                    'web_search',
                    0,
                    len(all_chunks),
                    'done',
                    'done',
                    'done',
                    'done',
                    '[]'
                )
                cursor.execute(uf_sql, uf_values)
                db.commit()
            except Exception as e_uf:
                print(f"MySQL Uploaded Files Error for web search: {e_uf}")
    except Exception as e:
        print(f"MySQL Normalized Knowledge Error: {e}")
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

    return True, f"Stored {len(all_chunks)} text chunks."

def ingest_web_search(company_code: str, session_id: str, query: str, ai_response: str = None, workspace_id: str = None, ingest_to_vector_graph: bool = False, created_by: str = None):
    """
    Pipeline for live web search data.
    """
    # 1. Use provided ai_response or fetch live data
    if ai_response:
        live_data = ai_response
    else:
        live_data = live_web_search(query)
        if "Error" in live_data or "No recent" in live_data:
            return False, live_data
        
    # Bypass CSV entirely
    source_name = f"web_search_{query.replace(' ', '_')[:20]}"
    return process_and_store_text(company_code, session_id, live_data, source_name, workspace_id, ingest_to_vector_graph=ingest_to_vector_graph, created_by=created_by)
    
def ingest_uploaded_csv(company_code: str, session_id: str, file_path: str, workspace_id: str = None, ingest_to_vector_graph: bool = False):
    """
    Pipeline for user uploaded CSV.
    """
    try:
        df = pd.read_csv(file_path)
        import os
        filename = os.path.basename(file_path)
        return process_and_store_data(company_code, session_id, df, filename, workspace_id, ingest_to_vector_graph=ingest_to_vector_graph)
    except Exception as e:
        return False, f"CSV Processing Error: {e}"
