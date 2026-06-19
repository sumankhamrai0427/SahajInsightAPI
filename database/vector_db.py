import os
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
    collection_name = f"{company_code}_rag_docs"
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

def query_chroma(company_code: str, query_text: str, n_results: int = 5, workspace_id: str = None):
    """
    Semantically search the vector DB for the most relevant chunks.
    Filters by workspace_id if provided.
    """
    collection = get_or_create_collection(company_code)
    
    query_args = {
        "query_texts": [query_text],
        "n_results": n_results
    }
    
    if workspace_id:
        query_args["where"] = {"workspace_id": str(workspace_id)}
        
    results = collection.query(**query_args)
    
    return results

def delete_collection(company_code: str):
    """
    Deletes an entire collection. Useful for resetting.
    """
    collection_name = f"{company_code}_rag_docs"
    import re
    collection_name = re.sub(r'[^a-zA-Z0-9_]', '_', collection_name)
    try:
        chroma_client.delete_collection(name=collection_name)
        return True
    except ValueError:
        return False
