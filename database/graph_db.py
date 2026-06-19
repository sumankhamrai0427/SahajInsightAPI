import os
from arango import ArangoClient
from dotenv import load_dotenv

load_dotenv()

ARANGO_URL = os.getenv("ARANGO_URL")
ARANGO_USER = os.getenv("ARANGO_USER", "root")
ARANGO_PASSWORD = os.getenv("ARANGO_PASSWORD", "")
ARANGO_DB_NAME = os.getenv("ARANGO_DB", "sahaj_insights")

# Global client cache
_db_cache = None

def get_graph_db():
    """
    Connects to ArangoDB and returns the database instance.
    Creates the database if it doesn't exist (if user has permissions).
    """
    global _db_cache
    if _db_cache is not None:
        return _db_cache

    if not ARANGO_URL:
        print("[ArangoDB] Missing ARANGO_URL in .env")
        return None

    try:
        client = ArangoClient(hosts=ARANGO_URL)
        sys_db = client.db('_system', username=ARANGO_USER, password=ARANGO_PASSWORD)
        
        if not sys_db.has_database(ARANGO_DB_NAME):
            sys_db.create_database(ARANGO_DB_NAME)
            
        _db_cache = client.db(ARANGO_DB_NAME, username=ARANGO_USER, password=ARANGO_PASSWORD)
        return _db_cache
    except Exception as e:
        print(f"[ArangoDB Connection Error] {e}")
        return None

def ensure_graph_collections(company_code: str):
    """
    Ensures the vertex and edge collections exist for the given company.
    """
    db = get_graph_db()
    if not db: return None, None
    
    # We will use one vertex collection and one edge collection per company
    # Alternatively, we could use a single global collection and filter by company_code.
    # We'll use one collection per company to ensure isolation.
    import re
    safe_code = re.sub(r'[^a-zA-Z0-9_]', '_', company_code)
    
    vertex_col_name = f"nodes_{safe_code}"
    edge_col_name = f"edges_{safe_code}"
    
    if not db.has_collection(vertex_col_name):
        db.create_collection(vertex_col_name)
        
    if not db.has_collection(edge_col_name):
        db.create_collection(edge_col_name, edge=True)
        
    return db.collection(vertex_col_name), db.collection(edge_col_name)

def add_graph_data(company_code: str, entities: list, relationships: list):
    """
    Adds entities and relationships to the company's graph.
    entities: list of dicts: [{"_key": "product_1", "type": "Product", "name": "Pampers"}, ...]
    relationships: list of dicts: [{"_from": "nodes_xyz/product_1", "_to": "nodes_xyz/cat_1", "type": "belongs_to"}]
    """
    nodes_col, edges_col = ensure_graph_collections(company_code)
    if not nodes_col or not edges_col: return

    # Upsert nodes
    for entity in entities:
        if not entity.get('_key'):
            continue
        try:
            if not nodes_col.has(entity['_key']):
                nodes_col.insert(entity)
            else:
                nodes_col.update(entity)
        except Exception as e:
            print(f"[ArangoDB] Node Insert Error: {e}")

    # Upsert edges
    for rel in relationships:
        if not rel.get('_from') or not rel.get('_to'):
            continue
        try:
            # ArangoDB needs _from and _to to be standard "collection/key" strings
            # If they don't have the collection prefix, we add it.
            if '/' not in rel['_from']:
                rel['_from'] = f"{nodes_col.name}/{rel['_from']}"
            if '/' not in rel['_to']:
                rel['_to'] = f"{nodes_col.name}/{rel['_to']}"
                
            # Create a deterministic key for the edge
            import hashlib
            edge_id_str = f"{rel['_from']}_{rel['type']}_{rel['_to']}"
            rel['_key'] = hashlib.md5(edge_id_str.encode()).hexdigest()
            
            if not edges_col.has(rel['_key']):
                edges_col.insert(rel)
        except Exception as e:
            print(f"[ArangoDB] Edge Insert Error: {e}")

def query_graph_context(company_code: str, search_terms: list, workspace_id: str = None):
    """
    Given a list of entity names/terms, query ArangoDB for their neighbors.
    """
    db = get_graph_db()
    if not db: return []
    
    import re
    safe_code = re.sub(r'[^a-zA-Z0-9_]', '_', company_code)
    vertex_col_name = f"nodes_{safe_code}"
    edge_col_name = f"edges_{safe_code}"
    
    if not db.has_collection(vertex_col_name) or not db.has_collection(edge_col_name):
        return []

    # Simplified graph search: Find nodes matching the search terms, 
    # then traverse 1-step to find related entities.
    context = []
    
    ws_filter = f'AND v.workspace_id == "{workspace_id}"' if workspace_id else ""
    
    for term in search_terms:
        # Prevent AQL injection
        term_safe = term.replace('"', '').replace('\\', '')
        
        aql = f"""
        FOR v IN {vertex_col_name}
            FILTER (v.name LIKE "%{term_safe}%" OR v._key LIKE "%{term_safe}%") {ws_filter}
            LIMIT 3
            FOR neighbor, edge IN 1..1 ANY v {edge_col_name}
            RETURN {{
                "source": v.name,
                "relationship": edge.type,
                "target": neighbor.name
            }}
        """
        try:
            cursor = db.aql.execute(aql)
            for doc in cursor:
                context.append(doc)
        except Exception as e:
            print(f"[ArangoDB] AQL Error: {e}")
            
    return context
