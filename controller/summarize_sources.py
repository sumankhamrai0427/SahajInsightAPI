from flask import request, g
from model.llm_client import call_llm
from helper.helperFunctions import build_response

def summarize_sources_controller():
    try:
        body = request.get_json() or {}
        
        session_id = body.get("session_id")
        created_by = body.get("created_by")
        csv_files = body.get("csv_files", [])
        web_searches = body.get("web_searches", [])
        
        if not session_id or not created_by:
            return build_response(False, "session_id and created_by are required", 400)
            
        if not csv_files and not web_searches:
            return build_response(False, "Please select at least one source (CSV file or web search) to summarize.", 400)
            
        if not hasattr(g, "company_db"):
            return build_response(False, "Invalid session", 401)
            
        con = g.company_db
        cursor = con.cursor(dictionary=True)
        
        sources_details = []
        
        # 1. Fetch details of CSV files
        for fname in csv_files:
            cursor.execute("""
                SELECT file_name, table_name, insights, last_inserted_rows as rows_effected, total_columns 
                FROM uploaded_files 
                WHERE file_name = %s
            """, (fname,))
            row = cursor.fetchone()
            if row:
                sources_details.append({
                    "type": "CSV File",
                    "file_name": row["file_name"],
                    "table_name": row["table_name"],
                    "insights": row["insights"] or "No detailed insights found.",
                    "rows_count": row["rows_effected"] or 0,
                    "columns_count": row["total_columns"] or 0
                })
            else:
                sources_details.append({
                    "type": "CSV File",
                    "file_name": fname,
                    "error": "File record not found in system."
                })
                
        # 2. Fetch details of LLM Web Searches
        for sname in web_searches:
            cursor.execute("""
                SELECT content 
                FROM normalized_knowledge 
                WHERE source_type = 'web_search' AND source_name = %s
                LIMIT 10
            """, (sname,))
            rows = cursor.fetchall()
            if rows:
                content_samples = "\n".join([r["content"] for r in rows if r["content"]])
                if len(content_samples) > 2500:
                    content_samples = content_samples[:2500] + "... (truncated)"
                sources_details.append({
                    "type": "LLM Web Search",
                    "source_name": sname,
                    "content_samples": content_samples
                })
            else:
                sources_details.append({
                    "type": "LLM Web Search",
                    "source_name": sname,
                    "error": "Web search content not found in system."
                })
                
        cursor.close()
        
        # 3. Construct Prompt for LLM
        prompt = "You are an AI assistant analyzing datasets. The user has selected the following CSV files and LLM Web Search history items to import/summarize.\n\n"
        prompt += "Please provide a detailed, premium-quality summary explaining:\n"
        prompt += "1. The Topic/Domain of the selected data.\n"
        prompt += "2. The Content/Details found in these sources.\n"
        prompt += "3. The Motive/Objective/Purpose of analyzing these combined sources.\n"
        prompt += "4. A brief, actionable insight or synthesis of how they relate.\n\n"
        prompt += "Format your output with clean Markdown (use headings, bullet points, and highlight key terms). Keep the tone professional, engaging, and premium.\n\n"
        prompt += "Selected Sources Details:\n"
        
        for idx, src in enumerate(sources_details):
            prompt += f"\n--- Source {idx+1}: {src['type']} ---\n"
            if src["type"] == "CSV File":
                prompt += f"File Name: {src.get('file_name')}\n"
                prompt += f"Table Name in DB: {src.get('table_name')}\n"
                prompt += f"Rows: {src.get('rows_count')}, Columns: {src.get('columns_count')}\n"
                prompt += f"Insights/Summary: {src.get('insights')}\n"
            else:
                prompt += f"Query/Source Name: {src.get('source_name')}\n"
                prompt += f"Extracted Chunks Content:\n{src.get('content_samples')}\n"
                
        # 4. Call LLM
        ai_summary = call_llm(prompt)
        
        return build_response(True, "Summary generated successfully", 200, data={"summary": ai_summary})
        
    except Exception as e:
        return build_response(False, f"Server Error during summarization: {str(e)}", 500)
