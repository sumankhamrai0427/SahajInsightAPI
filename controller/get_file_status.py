from flask import request,g
from database.dbConnection import get_db_connection
from helper.helperFunctions import build_response


def get_file_status_controller():
    try:
        body = request.get_json()

        created_by = body.get("created_by")
        session_id = body.get("session_id")
        workspace_id = body.get("workspace_id")

        # VALIDATION
        if not created_by:
            return build_response(False, "created_by is required", 400, status="failed")

        if not session_id or not workspace_id:
            return build_response(False, "session_id and workspace_id are required", 400, status="failed")
        
         # -----------------------------
        # COMPANY DB MUST ALREADY EXIST
        # (set by attach_company_db)
        # -----------------------------
        if not hasattr(g, "company_db"):
            return build_response(False, "Invalid session", 401)



        con = g.company_db
        cursor = con.cursor(dictionary=True)

        # FETCH ALL FILES for the workspace
        # If workspace_id is provided, anyone in the workspace sees it.
        # If not, fallback to created_by + session_id
        fmt_time = '%H:%i:%s'
        fmt_date = '%d-%m-%Y'
        if workspace_id == "all":
            uf_where = "1=1"
            nk_where = "1=1"
            query_params = (fmt_time, fmt_date, fmt_time, fmt_date)
        elif workspace_id:
            uf_where = "uf.workspace_id = %s"
            nk_where = "nk.workspace_id = %s"
            query_params = (fmt_time, fmt_date, workspace_id, fmt_time, fmt_date, workspace_id)
        else:
            uf_where = "uf.created_by = %s AND uf.session_id = %s"
            nk_where = "nk.session_id = %s"
            query_params = (fmt_time, fmt_date, created_by, session_id, fmt_time, fmt_date, session_id)

        sql = f"""
        SELECT * FROM (
            SELECT 
                COALESCE(w.workspace_name, 'N/A') AS workspace_name,
                uf.workspace_id,
                uf.id AS file_id,
                uf.file_name,
                uf.table_name,
                uf.file_size_mb,
                uf.file_type,
                uf.last_inserted_rows as rows_effected,
                uf.total_columns,
                COALESCE(uf.table_extraction_status, 'pending') AS table_extraction_status,
                COALESCE(uf.column_extraction_status, 'pending') AS column_extraction_status,
                COALESCE(uf.data_insights_status, 'pending') AS data_insights_status,
                COALESCE(uf.data_insert_status, 'pending') AS data_insert_status,
                uf.insights,
                (SELECT COUNT(*) FROM query_history qh WHERE JSON_CONTAINS(qh.table_names, JSON_QUOTE(uf.table_name))) AS connected_queries,
                (SELECT COUNT(*) FROM saved_reports sr JOIN query_history qh ON qh.id = sr.query_history_id WHERE JSON_CONTAINS(qh.table_names, JSON_QUOTE(uf.table_name))) AS connected_reports,
                (SELECT JSON_ARRAYAGG(qh.query_title) FROM query_history qh WHERE JSON_CONTAINS(qh.table_names, JSON_QUOTE(uf.table_name))) AS query_titles,
                (SELECT JSON_ARRAYAGG(sr.report_name) FROM saved_reports sr JOIN query_history qh ON qh.id = sr.query_history_id WHERE JSON_CONTAINS(qh.table_names, JSON_QUOTE(uf.table_name))) AS report_names,
                TIME_FORMAT(uf.created_at, %s) AS created_at,
                DATE_FORMAT(uf.created_at, %s) AS created_date,
                COALESCE(uf.updated_at, uf.created_at) AS updated_at
            FROM uploaded_files uf
            LEFT JOIN workspaces w ON uf.workspace_id = w.id
            WHERE {uf_where}
              AND (uf.file_type != 'web_search' OR uf.id = (
                  SELECT MAX(uf3.id) 
                  FROM uploaded_files uf3 
                  WHERE uf3.file_name = uf.file_name 
                    AND uf3.file_type = 'web_search'
                    AND (uf3.workspace_id = uf.workspace_id OR (uf3.workspace_id IS NULL AND uf.workspace_id IS NULL))
              ))
            
            UNION ALL
            
            SELECT 
                COALESCE(MAX(w.workspace_name), 'N/A') AS workspace_name,
                MAX(nk.workspace_id) AS workspace_id,
                MAX(nk.id) + 100000 AS file_id,
                nk.source_name AS file_name,
                'Web Search Data' AS table_name,
                '0 MB' AS file_size_mb,
                'web_search' AS file_type,
                COUNT(*) AS rows_effected,
                0 AS total_columns,
                'done' AS table_extraction_status,
                'done' AS column_extraction_status,
                'done' AS data_insights_status,
                'done' AS data_insert_status,
                '[]' AS insights,
                0 AS connected_queries,
                0 AS connected_reports,
                '[]' AS query_titles,
                '[]' AS report_names,
                TIME_FORMAT(MAX(nk.created_at), %s) AS created_at,
                DATE_FORMAT(MAX(nk.created_at), %s) AS created_date,
                MAX(nk.created_at) AS updated_at
            FROM normalized_knowledge nk
            LEFT JOIN workspaces w ON nk.workspace_id = w.id
            WHERE nk.source_type = 'web_search' AND {nk_where}
              AND NOT EXISTS (
                  SELECT 1 FROM uploaded_files uf2 
                  WHERE uf2.file_name = nk.source_name 
                    AND uf2.file_type = 'web_search'
                    AND (uf2.workspace_id = nk.workspace_id OR (uf2.workspace_id IS NULL AND nk.workspace_id IS NULL))
              )
            GROUP BY nk.source_name
        ) AS combined_results
        ORDER BY updated_at DESC
        """
        cursor.execute(sql, query_params)
        result = cursor.fetchall()

        cursor.close()
       

        # NO DATA FOUND
        if not result:
            return build_response(
                True,
                "No data found",
                200,
                data=[],
                status="success"
            )
        # SUCCESS RESPONSE
        return build_response(
            True,
            "Status fetched successfully",
            200,
            data=result,
            status="success"
        )

    except Exception as e:
        return build_response(
            False,
            "Server Error",
            500,
            data={"error": str(e)},
            status="error"
        )