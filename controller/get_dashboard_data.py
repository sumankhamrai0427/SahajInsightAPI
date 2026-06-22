from flask import request,g
from helper.helperFunctions import build_response


def get_dashboard_data_controller():
    try:
        body = request.get_json() or {}
        created_by = body.get("created_by")
        session_id = body.get("session_id")

        # -----------------------------
        # BASIC VALIDATION
        # -----------------------------
        if not created_by or not session_id:
            return build_response(False, "created_by & session_id required", 400)

        # -----------------------------
        # COMPANY DB MUST ALREADY EXIST
        # (set by attach_company_db)
        # -----------------------------
        if not hasattr(g, "company_db"):
            return build_response(False, "Invalid session", 401)

        db = g.company_db
        cursor = db.cursor(dictionary=True)

        # -----------------------------
        # VALIDATE USER SESSION
        # -----------------------------
        cursor.execute("""
            SELECT user_id
            FROM users
            WHERE user_id = %s
              AND session_id = %s
            LIMIT 1
        """, (created_by, session_id))

        if not cursor.fetchone():
            cursor.close()
            return build_response(False, "Invalid session_id or created_by", 401)

        # -----------------------------
        # CALL STORED PROCEDURE
        # -----------------------------
        cursor.callproc("sp_get_dashboard_data", (session_id, created_by))

        result_sets = []
        for rs in cursor.stored_results():
            result_sets.append(rs.fetchall())

        cursor.close()

        # -----------------------------
        # SAFE EXTRACTOR
        # -----------------------------
        def safe_get(rs_list, key, default=0):
            if rs_list and len(rs_list) > 0:
                val = rs_list[0].get(key, default)
                return default if val is None else val
            return default

        # -----------------------------
        # RESPONSE
        # -----------------------------
        dashboard_data = {
            "total_uploaded_files": safe_get(result_sets[0], "total_uploaded_files"),
            "total_extracted_files": safe_get(result_sets[1], "table_extract_status"),
            "total_reports_generated": safe_get(result_sets[2], "total_reports_generated"),
            "total_queries": safe_get(result_sets[3], "total_queries"),
            "working_queries": safe_get(result_sets[4], "working_queries"),
            "latest_file": (
                result_sets[5][0]
                if len(result_sets) > 5 and result_sets[5]
                else None
            ),
            "avg_query_time": safe_get(result_sets[6], "avg_query_time"),
            "query_success_rate": safe_get(result_sets[7], "query_success_rate"),
            "avg_rows_per_report": safe_get(result_sets[8], "avg_rows_per_report"),
            "file_upload_trend": result_sets[9] if len(result_sets) > 9 else [],
            "query_activity_trend": result_sets[10] if len(result_sets) > 10 else [],
            "top_tables_used": result_sets[11] if len(result_sets) > 11 else []
        }

        return build_response(True, "Dashboard data retrieved", 200, dashboard_data)

    except Exception as e:
        return build_response(
            False,
            "Failed to retrieve dashboard data",
            500,
            {"error": str(e)}
        )
