import json
import re
from flask import request,g
from helper.helperFunctions import build_response, format_dates_in_rows
from model.llm_client import call_llm
from helper.visualization_engine import build_insights,is_groupby_allowed,get_column_types
import time
COLUMN_SYNONYMS = {
    "blood group": "blood_group",
    "bloodgroup": "blood_group",
    "bg": "blood_group",
    "dept": "department_id",
    "department": "department_id"
}

def is_aggregation_query(select_query: str):
    select_query = select_query.lower()

    return (
        "count(" in select_query or
        "sum(" in select_query or
        "avg(" in select_query or
        "min(" in select_query or
        "max(" in select_query
    )


def extract_tables_and_columns_from_query(user_query, schema_context):
    words = re.findall(r"\b[a-zA-Z_]+\b", user_query.lower())

    schema_tables = set(schema_context.keys())
    schema_columns = {
        col.lower(): table
        for table, cols in schema_context.items()
        for col in cols
    }

    mentioned_tables = set()
    mentioned_columns = []

    # ---- detect table mentions ----
    for i, w in enumerate(words):
        # pattern: "from department table"
        if w == "table" and i > 0:
            mentioned_tables.add(words[i - 1])

        # direct table name mention
        if w in schema_tables:
            mentioned_tables.add(w)

    # ---- detect column mentions ----
    for w in words:
        if w in schema_columns:
            mentioned_columns.append((w, schema_columns[w]))

    return mentioned_tables, mentioned_columns

def validate_tables_and_columns_pre_llm(user_query, schema_context):
    mentioned_tables, mentioned_columns = extract_tables_and_columns_from_query(
        user_query, schema_context
    )

    errors = []

    # table validation
    for t in mentioned_tables:
        if t not in schema_context:
            errors.append(f"Table '{t}' does not exist")

    # column validation (STRICT)
    for col, table in mentioned_columns:
        if col not in [c.lower() for c in schema_context.get(table, [])]:
            errors.append(f"Column '{col}' does not exist in table '{table}'")

    #  IMPORTANT: if user mentioned a column via synonym but it's not in schema
    text = user_query.lower()
    for phrase, real_col in COLUMN_SYNONYMS.items():
        if phrase in text:
            found = False
            for cols in schema_context.values():
                if real_col in [c.lower() for c in cols]:
                    found = True
            if not found:
                errors.append(f"Column '{real_col}' does not exist in table 'students'")

    if errors:
        return False, list(set(errors))

    return True, None


def is_safe_select(sql):
    sql = sql.strip()

    # must start with SELECT
    if not re.match(r"^SELECT\b", sql, re.IGNORECASE):
        return False

    # block only whole forbidden keywords
    # forbidden_pattern = r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|REPLACE)\b"
    forbidden_pattern = r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|TRUNCATE|CREATE|REPLACE|SHOW|COMMIT|ROLLBACK|SAVEPOINT|SET)\b"

    if re.search(forbidden_pattern, sql, re.IGNORECASE):
        return False

    return True

def ask_llm_for_sp_name(user_query):
    prompt = f"""
    You must generate ONLY a short MySQL stored procedure name based on this query:

    "{user_query}"

    RULES:
    - Must be short (2-4 meaningful words)
    - Must use snake_case
    - MUST start with: sp_
    - MUST contain ONLY letters, numbers, and underscores
    - Do NOT return explanations
    - Do NOT return SQL
    - Return ONLY the procedure name
    """

    name = call_llm(prompt).strip()
    name = name.replace("`", "").replace(";", "")

    # safety filter
    name = re.sub(r'[^a-zA-Z0-9_]', '', name)

    return name


def chat_endpoint_controller():
    try:
        data = request.get_json() or {}
        session_id = data.get("session_id")
        # created_by = data.get("created_by")
        user_query = data.get("user_query")

        if not all([session_id,  user_query]):
            return build_response(False, "Missing required fields", 400)
        
        # -----------------------------
        # COMPANY DB MUST ALREADY EXIST
        # (set by attach_company_db)
        # -----------------------------
        # company db attach
        if not hasattr(g, "company_db") or not hasattr(g, "created_by"):
            return build_response(False, "Invalid session", 401)

        created_by = g.created_by   #  THIS IS IMPORTANT
        workspace_id = data.get("workspace_id")
        # ======================================================
        # STEP 1 — Fetch table names from uploaded_files
        # ======================================================
        conn = g.company_db
        cursor = conn.cursor(dictionary=True)

        if workspace_id and str(workspace_id).lower() not in ("null", "undefined", ""):
            cursor.execute("""
                SELECT table_name 
                FROM uploaded_files  
                WHERE workspace_id=%s
                  AND table_extraction_status='done'
                  AND column_extraction_status='done'
            """, (workspace_id,))
        else:
            cursor.execute("""
                SELECT table_name 
                FROM uploaded_files  
                WHERE session_id=%s
                  AND created_by=%s
                  AND table_extraction_status='done'
                  AND column_extraction_status='done'
            """, (session_id, created_by))

        table_rows = cursor.fetchall()

        if not table_rows:
            return build_response(False, "No tables found for this session", 404)

        table_names = [t["table_name"] for t in table_rows]

        # ======================================================
        # STEP 2 — Fetch FULL TABLE DATA + schema
        # ===================== full_table_data = {}
        schema_context = {}

        for tname in table_names:
            cursor.execute(f"SELECT * FROM `{tname}`")
            rows = cursor.fetchall()

            # schema_context[tname] = list(rows[0].keys()) if rows else []
            if rows:
                schema_context[tname] = [
                    col for col in rows[0].keys()
                    if col.lower() != "row_hash"
                ]
            else:
                schema_context[tname] = []

        cursor.close()

    
        # ======================================================
        # STEP 2.5 — PRE-LLM schema validation
        # ======================================================
        ok, errors = validate_tables_and_columns_pre_llm(user_query, schema_context)

        if not ok:
            return build_response(
                False,
                "; ".join(errors),
                400
            )
    
    
        # ======================================================
        # STEP 3 — Build schema JSON for LLM
        # ======================================================
        schema_json = json.dumps(schema_context, indent=2)
        sp_name = ask_llm_for_sp_name(user_query)
        system_instruction = f"""
You are a MySQL 8.0 expert.

STRICT OUTPUT RULES:
------------------------------------
1. Output MUST be ONLY this format:

DELIMITER ;;
CREATE PROCEDURE {sp_name}()
BEGIN
    <SQL QUERY HERE>
END;;
DELIMITER ;

2. NO extra text
3. NO comments
4. NO markdown
5. NO explanation
6. NEVER change procedure name
7. Use ONLY tables and columns listed below:

TABLES YOU CAN USE:
{schema_json}

COLUMN RULES:
- Map user keywords semantically to correct columns.
- Never invent new columns.
- Always prefix columns with table name.
- Follow ONLY_FULL_GROUP_BY rules.
IMPLICIT FILTER RULES:
- If user gives a column name followed by a value without specifying an operator 
  (e.g., 'name Ali', 'customer Ali', 'status pending'),
  automatically convert it into SQL using LIKE '%value%'.
- Do not output explanation or reasoning; only generate SQL inside the stored procedure.
ABSOLUTE SECURITY RULES:
- NEVER generate SHOW queries
- NEVER generate CREATE / DROP / ALTER
- NEVER generate INSERT / UPDATE / DELETE
- NEVER generate COMMIT / ROLLBACK / SAVEPOINT
- NEVER generate SET TRANSACTION or SET commands

------------------------------------
"""

        user_prompt = f"User Query: {user_query}\nGenerate MySQL stored procedure only."

        # ======================================================
        # STEP 4 — Merge prompts + Call LLM
        # ======================================================
        final_prompt = system_instruction + "\n" + user_prompt
        ai_sql = call_llm(final_prompt).strip()
        select_query = extract_select_query(ai_sql)

        # must extract ONE SELECT
        if not select_query:
            return build_response(
                False,
                "Invalid SQL generated. Only one SELECT statement is allowed.",
                400
            )

        # block DDL / DML / TCL / SET / non-SELECT
        if not is_safe_select(select_query):
            return build_response(
                False,
                "Unsafe SQL generated. Only read-only SELECT queries are allowed.",
                400
            )

        # ======================================================
        # STEP 5 — Response
        # ======================================================
        return build_response(True, "Chat processed", 200, {
            "session_id": session_id,
            "tables": table_names,
            "schema_context": schema_context,
            "ai_response": ai_sql
        })

    except Exception as e:
        return build_response(False, f"Chat Error: {e}", 500)


def format_execution_time(seconds):
    # If below 1 hour
    if seconds < 60:
        return f"{round(seconds, 3)} sec"
    
    # If 1 minute up to 1 hour
    if seconds < 3600:
        minutes = seconds / 60
        return f"{round(minutes, 2)} minutes"
    
    # If more than 1 hour
    hours = seconds / 3600
    return f"{round(hours, 2)} hours"

def extract_select_query(ai_response):
    # Remove delimiters
    clean = ai_response.replace("DELIMITER ;;", "").replace("DELIMITER ;", "")

    # Remove CREATE PROCEDURE and BEGIN / END block
    clean = re.sub(r"CREATE\s+PROCEDURE[\s\S]*?BEGIN", "", clean, flags=re.IGNORECASE)
    # clean = re.sub(r"END\s*;?", "", clean, flags=re.IGNORECASE)
    clean = re.sub(r"\bEND\b\s*;?", "", clean, flags=re.IGNORECASE)


    # Extract only SELECT query
    match = re.search(r"(SELECT[\s\S]*?);", clean, flags=re.IGNORECASE)
    
    if match:
        return match.group(1).strip()  # return only the SELECT statement
    
    return None  # if not found



def run_select_query(select_query):
    try:
        # -----------------------------
        conn = g.company_db
        cursor = conn.cursor(dictionary=True)

        start_time = time.time()   # ⏱️ START
        # g.last_used_table = extract_main_table_from_query(select_query)
        g.last_used_table = extract_main_table_from_query(select_query)
        select_query = sanitize_group_by(select_query, g.last_used_table)

        cursor.execute(select_query)

        # cursor.execute(select_query)
        rows = cursor.fetchall()
        rows = format_dates_in_rows(rows)
          #  REMOVE row_hash FROM ROW DATA
        for r in rows:
            r.pop("row_hash", None)

        end_time = time.time()     #  END
        elapsed = end_time - start_time
        #  REMOVE row_hash FROM COLUMNS
        column_names = [
            desc[0] for desc in cursor.description
            if desc[0].lower() != "row_hash"
        ]
        # column_names = [desc[0] for desc in cursor.description]

        cursor.close()
        # conn.close()

        return True, {
            "columns": column_names,
            "rows": rows,
            "total_rows": len(rows),
            "execution_time": format_execution_time(elapsed)  # ✅ HERE
        }, "OK"

    except Exception as e:
        return False, None, str(e)

def extract_main_table_from_query(sql):
    import re
    match = re.search(r"\bFROM\s+`?(\w+)`?", sql, re.IGNORECASE)
    return match.group(1) if match else None

def sanitize_group_by(select_sql: str, table_name: str):
    # if not is_aggregation_query(select_sql):
    #     return re.sub(r"\s+GROUP BY\s+.*", "", select_sql, flags=re.IGNORECASE)
    #  MINIMAL FIX — aggregation query hole GROUP BY touch korbe na
    if is_aggregation_query(select_sql):
        return select_sql
    col_types = get_column_types(table_name)

    match = re.search(r"GROUP BY\s+(.*)", select_sql, re.IGNORECASE)
    if not match:
        return select_sql

    group_cols = [
        c.strip().replace("`", "")
        for c in match.group(1).split(",")
    ]

    safe_cols = []
    for col in group_cols:
        col_name = col.split(".")[-1]
        ctype = col_types.get(col_name)

        if ctype and is_groupby_allowed(col_name, ctype):
            safe_cols.append(col)

    if not safe_cols:
        return re.sub(r"\s+GROUP BY\s+.*", "", select_sql, flags=re.IGNORECASE)

    safe_group = "GROUP BY " + ", ".join(safe_cols)
    return re.sub(
        r"GROUP BY\s+.*",
        safe_group,
        select_sql,
        flags=re.IGNORECASE
    )

def execute_sql_endpoint_controller():
    try:
        ai_sql = request.json.get("sql_query")

        if not ai_sql:
            return build_response(False, "Missing sql_query", 400)

        select_query = extract_select_query(ai_sql)
        if not select_query:
            return build_response(False, "Failed to extract SELECT query", 400)

        #  only SELECT allowed
        if not is_safe_select(select_query):
            return build_response(False, "Only SELECT queries are allowed", 400)
       
        success, results, msg = run_select_query(select_query)

        if success:


            # NORMAL TABLE QUERY (UNCHANGED)
            total = results.get("total_rows", 0)

            table_name = g.get("last_used_table")
            visualization = build_insights(
                table_name,
                results.get("columns", [])
            )

            results["visualization"] = visualization

            msg = "Query executed successfully, but no data found." if total == 0 \
                else f"Successfully fetched {total} rows."

            return build_response(True, msg, 200, results)


        return build_response(False, msg, 400)

    except Exception as e:
        return build_response(False, f"Server Error: {e}", 500)
