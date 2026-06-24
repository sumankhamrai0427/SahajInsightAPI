import os
try:
    import numpy as np
    np.float_ = np.float64
except ImportError:
    pass
import chromadb
from chromadb.config import Settings

# Get base path relative to this file
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VECTOR_STORE_PATH = os.path.join(BASE_DIR, "vector_store")

# Initialize ChromaDB client (Persistent)
chroma_client = chromadb.PersistentClient(path=VECTOR_STORE_PATH, settings=Settings(anonymized_telemetry=False))

def get_or_create_collection(company_code: str):
    """
    Returns the ChromaDB collection for a specific company.
    Creates it if it doesn't exist.
    """
    db_name = company_code
    if db_name and not db_name.startswith("sahaj_cmp_"):
        db_name = f"sahaj_cmp_{db_name}"
    collection_name = f"{db_name}_rag_docs"
    # Ensure collection name is valid (alphanumeric and underscores only)
    import re
    collection_name = re.sub(r'[^a-zA-Z0-9_]', '_', collection_name)
    
    return chroma_client.get_or_create_collection(name=collection_name)

def add_chunks_to_chroma(company_code: str, chunks: list, metadatas: list, ids: list):
    """
    Adds text chunks to the company's ChromaDB collection.
    Automatically handles embeddings using Chroma's default embedding function (all-MiniLM-L6-v2)
    or you can pass a custom one. We'll use the default which is small and fast.
    """
    if not chunks:
        return
        
    collection = get_or_create_collection(company_code)
    
    # Add to collection
    collection.add(
        documents=chunks,
        metadatas=metadatas,
        ids=ids
    )

def query_chroma(company_code: str, query_text: str, n_results: int = 5, workspace_id: str = None, session_id: str = None):
    """
    Semantically search the vector DB for the most relevant chunks.
    Filters by session_id if provided, with fallbacks to workspace_id or no filter.
    """
    collection = get_or_create_collection(company_code)
    
    query_args = {
        "query_texts": [query_text],
        "n_results": n_results
    }
    
    # Try querying with session_id filter first (if specified)
    if session_id:
        query_args["where"] = {"session_id": str(session_id)}
        try:
            results = collection.query(**query_args)
            if results and "documents" in results and results["documents"] and any(results["documents"]):
                return results
        except Exception as e:
            print(f"[ChromaDB Session Filter Query Error] {e}")
            
    # Try querying with workspace filter (if specified and not "all")
    if workspace_id and str(workspace_id).lower() != "all":
        query_args["where"] = {
            "$or": [
                {"workspace_id": str(workspace_id)},
                {"workspace_id": "all"}
            ]
        }
        try:
            results = collection.query(**query_args)
            if results and "documents" in results and results["documents"] and any(results["documents"]):
                return results
        except Exception as e:
            print(f"[ChromaDB Workspace Filter Query Error] {e}")
            
    # Fallback: Query all documents in the company collection without any filter
    if "where" in query_args:
        del query_args["where"]
        
    return collection.query(**query_args)

def delete_collection(company_code: str):
    """
    Deletes an entire collection. Useful for resetting.
    """
    db_name = company_code
    if db_name and not db_name.startswith("sahaj_cmp_"):
        db_name = f"sahaj_cmp_{db_name}"
    collection_name = f"{db_name}_rag_docs"
    import re
    collection_name = re.sub(r'[^a-zA-Z0-9_]', '_', collection_name)
    try:
        chroma_client.delete_collection(name=collection_name)
        return True
    except ValueError:
        return False
