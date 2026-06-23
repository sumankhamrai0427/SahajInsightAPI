from flask import request,g
from helper.helperFunctions import build_response


def delete_uploaded_file_controller():
    conn = None
    cursor = None

    try:
        data = request.get_json() or {}

        session_id = data.get("session_id")
        created_by = data.get("created_by")
        file_name = data.get("file_name")

        # -------------------------------
        # REQUIRED VALIDATION → 400 ONLY
        # -------------------------------
        if not session_id or not created_by or not file_name:
            return build_response(
                False,
                "session_id, created_by & file_name required",
                400
            )

        conn = g.company_db
        cursor = conn.cursor(dictionary=True)

        # -------------------------------
        # WEB SEARCH DELETE CHECK
        # -------------------------------
        cursor.execute("SELECT id, file_type FROM uploaded_files WHERE session_id = %s AND file_name = %s LIMIT 1", (session_id, file_name))
        uf_row = cursor.fetchone()
        
        is_web_search = False
        if uf_row and uf_row['file_type'] == 'web_search':
            is_web_search = True
        else:
            cursor.execute("SELECT COUNT(*) as count FROM normalized_knowledge WHERE session_id = %s AND source_type = 'web_search' AND source_name = %s", (session_id, file_name))
            nk_count = cursor.fetchone()
            if nk_count and nk_count['count'] > 0:
                is_web_search = True
                
        if is_web_search:
            cursor.execute("DELETE FROM normalized_knowledge WHERE session_id = %s AND source_type = 'web_search' AND source_name = %s", (session_id, file_name))
            cursor.execute("DELETE FROM uploaded_files WHERE session_id = %s AND file_type = 'web_search' AND file_name = %s", (session_id, file_name))
            conn.commit()
            return build_response(True, "Web Search Data deleted successfully", 200)

        # -------------------------------
        # CALL STORED PROCEDURE (v2)
        # -------------------------------
        cursor.callproc(
            "sp_delete_uploaded_file",
            [session_id, created_by, file_name]
        )

        results = list(cursor.stored_results())
        conn.commit()

        if not results:
            return build_response(
                False,
                "No response from delete procedure",
                200
            )

        # -------------------------------
        # RESULT SET 1 → STATUS MESSAGE
        # -------------------------------
        status_row = results[0].fetchone()
        status_msg = status_row.get("status", "Unknown status")

        # # -------------------------------
        # COLLECT DEPENDENCIES SAFELY
        # -------------------------------
        report_deps = []
        query_deps = []
        base_status = "Dependency exists"

        for rs in results:
            rows = rs.fetchall()
            for row in rows:
                if "status" in row:
                    base_status = row["status"]
                elif "report_id" in row:
                    report_deps.append(row)
                elif "query_title" in row:
                    query_deps.append(row)

        # -------------------------------
        # DEPENDENCY RESPONSE
        # -------------------------------
        if report_deps or query_deps:
            report_count = len(report_deps)
            query_count = len(query_deps)

            if report_count and query_count:
                status_msg = (
                    f'Table "{file_name}" is already used in '
                    f'{report_count} reports and {query_count} queries'
                )
            elif report_count:
                status_msg = (
                    f'Table "{file_name}" is already used in {report_count} reports'
                )
            else:
                status_msg = (
                    f'Table "{file_name}" is already used in {query_count} queries'
                )

            return build_response(
                False,
                status_msg,
                200,
                data={"dependencies": report_deps + query_deps}
            )
        
        if "deleted successfully" in status_msg.lower():
            return build_response(
                True,
                status_msg,
                200
            )

        # Other blocked cases (table missing, invalid session, etc.)
        return build_response(
            False,
            status_msg,
            200
        )

    except Exception as e:
        # Exception also returns 200 as per requirement
        return build_response(
            False,
            f"Delete Error: {str(e)}",
            200
        )

    finally:
        if cursor:
            cursor.close()