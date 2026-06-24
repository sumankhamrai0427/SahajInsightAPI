import pandas as pd
# pyrefly: ignore [missing-import]
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
    
    extracted_chunks_count = 0
    MAX_CSV_GRAPH_CHUNKS = 15
    
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
            
            # Extract graph data:
            # - Extract only if ingest_to_vector_graph is True
            # - For web_search: extract all chunks
            # - For CSVs: extract up to the first 15 chunks to limit LLM cost
            should_extract = False
            if ingest_to_vector_graph:
                if "web_search" in source_name:
                    should_extract = True
                elif extracted_chunks_count < MAX_CSV_GRAPH_CHUNKS:
                    should_extract = True
                
            if should_extract:
                nodes, edges = extract_entities_with_llm(chunk)
                if nodes or edges:
                    if "web_search" not in source_name:
                        extracted_chunks_count += 1
                    
                    # Normalize keys to connect identical entities and prevent duplicates
                    key_map = {}
                    normalized_nodes = []
                    for n in nodes:
                        old_key = n.get("_key")
                        name = n.get("name", "")
                        ntype = n.get("type", "Entity")
                        if not old_key or not name:
                            continue
                        
                        # Generate a clean, deterministic unique key based on type and name
                        safe_name = re.sub(r'[^a-z0-9_]', '_', name.lower().strip())
                        safe_type = re.sub(r'[^a-z0-9_]', '_', ntype.lower().strip())
                        new_key = f"{safe_type}_{safe_name}"
                        
                        n["_key"] = new_key
                        n["workspace_id"] = workspace_id
                        n["session_id"] = session_id
                        key_map[old_key] = new_key
                        normalized_nodes.append(n)
                        
                    normalized_edges = []
                    for e in edges:
                        frm = e.get("_from")
                        to = e.get("_to")
                        if not frm or not to:
                            continue
                        
                        # Map temporary LLM keys to our unique normalized keys
                        new_frm = key_map.get(frm, frm)
                        new_to = key_map.get(to, to)
                        
                        e["_from"] = new_frm
                        e["_to"] = new_to
                        e["workspace_id"] = workspace_id
                        e["session_id"] = session_id
                        normalized_edges.append(e)
                        
                    all_nodes.extend(normalized_nodes)
                    all_edges.extend(normalized_edges)

    # 1. Store in ChromaDB (Always)
    try:
        add_chunks_to_chroma(company_code, all_chunks, metadatas, ids)
    except Exception as e:
        return False, f"ChromaDB Error: {e}"

    # 2. Store in ArangoDB (Graph DB) only if requested
    if ingest_to_vector_graph and (all_nodes or all_edges):
        try:
            add_graph_data(company_code, all_nodes, all_edges)
        except Exception as e:
            print(f"ArangoDB Error: {e}")
            
        # Save HTML graph visualization locally
        try:
            save_graph_visualization(source_name, all_nodes, all_edges)
        except Exception as e:
            print(f"Graph Visual Save Error: {e}")

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
            
            # Delete existing chunks for this source and workspace to avoid duplicate chunks in MySQL
            if safe_workspace_id:
                cursor.execute(
                    "DELETE FROM normalized_knowledge WHERE source_name = %s AND source_type = %s AND workspace_id = %s",
                    (source_name, source_type, safe_workspace_id)
                )
            else:
                cursor.execute(
                    "DELETE FROM normalized_knowledge WHERE source_name = %s AND source_type = %s AND workspace_id IS NULL",
                    (source_name, source_type)
                )

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
                from flask import has_request_context
                if not has_request_context():
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
        
    if "--- Source:" in text:
        all_chunks = [chunk.strip() for chunk in text.split("\n\n") if chunk.strip()]
    else:
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
        
        # Extract graph data only if requested
        nodes, edges = ([], [])
        if ingest_to_vector_graph:
            nodes, edges = extract_entities_with_llm(chunk)
            
        if nodes or edges:
            key_map = {}
            normalized_nodes = []
            for n in nodes:
                old_key = n.get("_key")
                name = n.get("name", "")
                ntype = n.get("type", "Entity")
                if not old_key or not name:
                    continue
                
                safe_name = re.sub(r'[^a-z0-9_]', '_', name.lower().strip())
                safe_type = re.sub(r'[^a-z0-9_]', '_', ntype.lower().strip())
                new_key = f"{safe_type}_{safe_name}"
                
                n["_key"] = new_key
                n["workspace_id"] = workspace_id
                n["session_id"] = session_id
                key_map[old_key] = new_key
                normalized_nodes.append(n)
                
            normalized_edges = []
            for e in edges:
                frm = e.get("_from")
                to = e.get("_to")
                if not frm or not to:
                    continue
                
                new_frm = key_map.get(frm, frm)
                new_to = key_map.get(to, to)
                
                e["_from"] = new_frm
                e["_to"] = new_to
                e["workspace_id"] = workspace_id
                e["session_id"] = session_id
                normalized_edges.append(e)
                
            all_nodes.extend(normalized_nodes)
            all_edges.extend(normalized_edges)

    # 1. Store in ChromaDB (Always)
    try:
        add_chunks_to_chroma(company_code, all_chunks, metadatas, ids)
    except Exception as e:
        return False, f"ChromaDB Error: {e}"

    # 2. Store in ArangoDB (Graph DB) only if requested
    if ingest_to_vector_graph and (all_nodes or all_edges):
        try:
            add_graph_data(company_code, all_nodes, all_edges)
        except Exception as e:
            print(f"ArangoDB Error: {e}")
            
        # Save HTML graph visualization locally
        try:
            save_graph_visualization(source_name, all_nodes, all_edges)
        except Exception as e:
            print(f"Graph Visual Save Error: {e}")

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
            
            # Delete existing chunks for this source and workspace to avoid duplicate chunks in MySQL
            if safe_workspace_id:
                cursor.execute(
                    "DELETE FROM normalized_knowledge WHERE source_name = %s AND source_type = %s AND workspace_id = %s",
                    (source_name, source_type, safe_workspace_id)
                )
            else:
                cursor.execute(
                    "DELETE FROM normalized_knowledge WHERE source_name = %s AND source_type = %s AND workspace_id IS NULL",
                    (source_name, source_type)
                )

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

            # Insert/Update uploaded_files
            try:
                if safe_workspace_id:
                    cursor.execute(
                        "SELECT id FROM uploaded_files WHERE file_name = %s AND file_type = 'web_search' AND workspace_id = %s",
                        (source_name, safe_workspace_id)
                    )
                else:
                    cursor.execute(
                        "SELECT id FROM uploaded_files WHERE file_name = %s AND file_type = 'web_search' AND workspace_id IS NULL",
                        (source_name,)
                    )
                existing_uf = cursor.fetchone()
                if existing_uf:
                    # Update existing row
                    uf_sql = """
                        UPDATE uploaded_files 
                        SET last_inserted_rows = %s, updated_at = CURRENT_TIMESTAMP
                        WHERE id = %s
                    """
                    cursor.execute(uf_sql, (len(all_chunks), existing_uf[0]))
                else:
                    # Insert new row
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
                from flask import has_request_context
                if not has_request_context():
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

def save_graph_visualization(source_name: str, nodes: list, edges: list):
    """
    Saves a beautiful, interactive, self-contained force-directed graph visualization inside API/Graph/ folder.
    This runs 100% offline with vis-network.min.js inlined to avoid browser CORS/file-protocol blocking.
    """
    if not nodes and not edges:
        return
        
    try:
        import os
        # Create Graph folder if it doesn't exist
        graph_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "Graph")
        os.makedirs(graph_dir, exist_ok=True)
        
        # Safe filename
        safe_source_name = re.sub(r'[^a-zA-Z0-9_.-]', '_', source_name)
        file_path = os.path.join(graph_dir, f"{safe_source_name}.html")
        
        # Deduplicate nodes by _key
        unique_nodes = {}
        for n in nodes:
            key = n.get("_key")
            if key and key not in unique_nodes:
                unique_nodes[key] = n
                
        # Deduplicate edges by _from + _to + type
        unique_edges = {}
        for e in edges:
            frm = e.get("_from", "")
            to = e.get("_to", "")
            etype = e.get("type", "RELATED_TO")
            # ArangoDB style might contain nodes_xyz/ prefix, normalize it for local vis.js matching
            frm_clean = frm.split("/")[-1]
            to_clean = to.split("/")[-1]
            edge_key = f"{frm_clean}_{etype}_{to_clean}"
            if edge_key not in unique_edges:
                unique_edges[edge_key] = {
                    "from": frm_clean,
                    "to": to_clean,
                    "type": etype
                }
        
        # Color mapping by node type to support various entity types in business datasets
        colors_by_type = {
            "product": "#ff7b72",
            "category": "#79c0ff",
            "company": "#7ee787",
            "user": "#d2a8ff",
            "location": "#ffa657",
            "entity": "#58a6ff",
            "date": "#ffc857",
            "salesperson": "#ff9f1c",
            "customer": "#2ec4b6",
            "car": "#e71d36",
            "carmodel": "#ff6b6b",
            "cartype": "#a9def9",
            "color": "#e6adec",
            "price": "#ff99c8",
            "paymentmethod": "#fcf6bd",
            "region": "#d0f4de",
            "year": "#ffac81"
        }
        
        # Formatted nodes for visualization
        formatted_nodes = []
        for key, n in unique_nodes.items():
            ntype = n.get("type", "Entity")
            color = colors_by_type.get(ntype.lower(), "#58a6ff")
            formatted_nodes.append({
                "id": key,
                "label": n.get("name", key),
                "type": ntype,
                "color": color
            })
            
        # Formatted edges for visualization
        formatted_edges = []
        for e in unique_edges.values():
            formatted_edges.append({
                "from": e["from"],
                "to": e["to"],
                "label": e["type"]
            })
            
        html_template = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <title>Graph Visualization - {source_name}</title>
  <style type="text/css">
    body {
      background-color: #ffffff;
      color: #333333;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Helvetica, Arial, sans-serif;
      margin: 0;
      padding: 0;
      overflow: hidden;
      height: 100vh;
      width: 100vw;
    }
    #header {
      padding: 15px 20px;
      background-color: rgba(246, 248, 250, 0.9);
      border-bottom: 1px solid #d0d7de;
      display: flex;
      justify-content: space-between;
      align-items: center;
      position: absolute;
      top: 0;
      left: 0;
      right: 0;
      z-index: 10;
    }
    #header h1 {
      margin: 0;
      font-size: 16px;
      font-weight: 600;
      color: #24292f;
    }
    #header .stats {
      font-size: 12px;
      color: #57606a;
    }
    #network {
      width: 100%;
      height: 100%;
      position: absolute;
      top: 0;
      left: 0;
    }
    .badge {
      background-color: #0969da;
      color: #ffffff;
      padding: 3px 8px;
      border-radius: 10px;
      font-size: 11px;
      margin-left: 5px;
      font-weight: 600;
    }
  </style>
  <script type="text/javascript" src="https://unpkg.com/vis-network/standalone/umd/vis-network.min.js"></script>
</head>
<body>
  <div id="header">
    <h1>Graph Visualization: <span style="color: #0969da;">{source_name}</span></h1>
    <div class="stats">
      Entities: <span class="badge">{nodes_count}</span>
      Relationships: <span class="badge">{edges_count}</span>
    </div>
  </div>
  <div id="network"></div>

  <script type="text/javascript">
    var rawNodes = {raw_nodes};
    var rawEdges = {raw_edges};

    var nodes = new vis.DataSet(rawNodes.map(function(n) {
      var isCentral = n.type.toLowerCase() === 'transaction' || n.type.toLowerCase() === 'session';
      return {
        id: n.id,
        label: n.label,
        shape: 'dot',
        size: isCentral ? 24 : 16,
        color: {
          background: n.color || '#97c2fc',
          border: '#2b7ce9',
          highlight: {
            background: '#d2e5ff',
            border: '#2b7ce9'
          }
        },
        font: {
          size: 12,
          color: '#333333',
          face: 'sans-serif'
        },
        borderWidth: 1.5
      };
    }));

    var edges = new vis.DataSet(rawEdges.map(function(e) {
      return {
        from: e.from,
        to: e.to,
        label: e.label,
        arrows: {
          to: { enabled: true, scaleFactor: 0.6 }
        },
        color: {
          color: '#2b7ce9',
          highlight: '#2b7ce9',
          hover: '#2b7ce9'
        },
        font: {
          size: 10,
          color: '#333333',
          align: 'middle'
        },
        smooth: {
          type: 'continuous'
        }
      };
    }));

    var container = document.getElementById('network');
    var data = {
      nodes: nodes,
      edges: edges
    };
    
    var options = {
      physics: {
        stabilization: {
          enabled: true,
          iterations: 200
        },
        barnesHut: {
          gravitationalConstant: -15000,
          centralGravity: 0.1,
          springLength: 180,
          springConstant: 0.03,
          damping: 0.15
        }
      },
      interaction: {
        hover: true,
        tooltipDelay: 200,
        navigationButtons: true,
        keyboard: true
      }
    };
    
    var network = new vis.Network(container, data, options);
  </script>
</body>
</html>
"""
        
        # Perform string replacements
        html_content = html_template.replace("{source_name}", source_name)
        html_content = html_content.replace("{nodes_count}", str(len(formatted_nodes)))
        html_content = html_content.replace("{edges_count}", str(len(formatted_edges)))
        html_content = html_content.replace("{raw_nodes}", json.dumps(formatted_nodes))
        html_content = html_content.replace("{raw_edges}", json.dumps(formatted_edges))
        
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(html_content)
            
        print(f"[Graph Visualization] Saved inlined HTML to {file_path}")
    except Exception as e:
        print(f"[Graph Visualization Error] {e}")

