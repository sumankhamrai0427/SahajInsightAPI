from flask import request, g
from helper.helperFunctions import build_response
import json
import re

def extract_select_sql(ai_response):
    if not ai_response:
        return None
    clean = ai_response.replace("DELIMITER ;;", "").replace("DELIMITER ;", "")
    clean = re.sub(r"CREATE\s+PROCEDURE[\s\S]*?BEGIN", "", clean, flags=re.I)
    clean = re.sub(r"\bEND\b\s*;?", "", clean, flags=re.I)
    m = re.search(r"(SELECT[\s\S]*?);", clean, flags=re.I)
    return m.group(1).strip() if m else None


def extract_tables(sql):
    if not sql:
        return []
    found = re.findall(r"\bFROM\s+(\w+)|\bJOIN\s+(\w+)", sql, re.I)
    tables = set()
    for f in found:
        for t in f:
            if t:
                tables.add(t.lower())
    return list(tables)

def is_new_message(query_id):
    try:
        return int(query_id) >= 10**12
    except:
        return False


def query_save_controller():
    try:
        data = request.get_json()

        session_id = data.get("session_id")
        created_by = data.get("created_by")
        workspace_id = data.get("workspace_id")
        query_title = data.get("query_title")
        parent_query_id = data.get("parent_query_id")  # DB id (edit case)
        messages = data.get("messages", [])

        if not hasattr(g, "company_db"):
            return build_response(False, "Invalid session", 401)

        conn = g.company_db
        cursor = conn.cursor(dictionary=True)

        root_parent_id = parent_query_id  # will be decided below

        # =====================================
        # INSERT NEW MESSAGES
        # =====================================
        for idx, msg in enumerate(messages):

            query_id = msg.get("query_id")
            ai_response = msg.get("ai_response")
            executable_sql = extract_select_sql(ai_response)
            table_names = extract_tables(executable_sql)

            if not is_new_message(query_id):
                continue

            # FIRST SAVE → ROOT
            if root_parent_id is None and idx == 0:
                cursor.callproc("sp_save_query", [
                    session_id,
                    workspace_id,
                    created_by,
                    query_title,
                    query_id,
                    msg.get("query"),
                    ai_response,
                    executable_sql,              # SQL
                    json.dumps(table_names), 
                    msg.get("is_execute", 0),
                    msg.get("is_success", 0),
                    msg.get("row_count", 0),
                    msg.get("query_time"),
                    "NEW",
                    None
                ])

                # CORRECT WAY to get saved id
                result = list(cursor.stored_results())
                root_parent_id = result[0].fetchone()["saved_id"]

            else:
                cursor.callproc("sp_save_query", [
                    session_id,
                    workspace_id,
                    created_by,
                    query_title,
                    query_id,
                    msg.get("query"),
                    ai_response,
                    executable_sql,              # SQL
                    json.dumps(table_names), 
                    msg.get("is_execute", 0),
                    msg.get("is_success", 0),
                    msg.get("row_count", 0),
                    msg.get("query_time"),
                    "NEW",
                    root_parent_id
                ])

                # consume result (important)
                list(cursor.stored_results())

        # =====================================
        # UPDATE TITLE (EDIT MODE)
        # =====================================
        if root_parent_id and query_title:
            cursor.execute("""
                UPDATE query_history
                SET query_title = %s,
                    updated_at = NOW(),
                    updated_by = %s
                WHERE id = %s
                   OR parent_query_id = %s
            """, (
                query_title,
                created_by,
                root_parent_id,
                root_parent_id
            ))

        conn.commit()
        cursor.close()

        return build_response(True, "Saved successfully", 200)

    except Exception as e:
        return build_response(False, f"Save Error: {str(e)}", 500)

