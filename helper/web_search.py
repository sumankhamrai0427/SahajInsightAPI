import json
from duckduckgo_search import DDGS
import time

def live_web_search(query: str, max_results: int = 5) -> str:
    """
    Performs a live web search using DuckDuckGo.
    Returns a combined string of the snippets/content from the search results.
    """
    try:
        ddgs = DDGS()
        results = []
        
        # Use the text search functionality
        search_results = ddgs.text(query, max_results=max_results)
        
        for r in search_results:
            results.append(f"Source: {r.get('href', '')}\nTitle: {r.get('title', '')}\nContent: {r.get('body', '')}\n")
            
        combined_text = "\n---\n".join(results)
        
        if not combined_text.strip():
            return "No recent search results found."
            
        return combined_text
        
    except Exception as e:
        print(f"[Web Search Error] {e}")
        return f"Error performing web search: {e}"
