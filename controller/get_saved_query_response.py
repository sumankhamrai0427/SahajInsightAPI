from flask import request, g
from helper.helperFunctions import build_response


def get_saved_query_response_controller():
    try:
        body = request.get_json()
        created_by = body.get("created_by")
        session_id = body.get("session_id")

        if not created_by or not session_id:
            return build_response(False, "created_by & session_id required", 400)

        if not hasattr(g, "company_db"):
            return build_response(False, "Invalid session", 401)

        db = g.company_db
        cursor = db.cursor(dictionary=True)

        cursor.callproc(
            "sp_get_query_details_by_user_session_id",
            (created_by, session_id)
        )

        rows = []
        for rs in cursor.stored_results():
            rows.extend(rs.fetchall())

        cursor.close()

        if not rows:
            return build_response(True, "No data found", 200, {"queries": []})

        # =========================================
        # GROUP BY ROOT QUERY (IMPORTANT FIX)
        # =========================================
        query_map = {}

        for r in rows:
            # ROOT KEY
            root_id = r["parent_query_id"] or r["id"]

            if root_id not in query_map:
                query_map[root_id] = {
                    "id": root_id,                    #  THIS IS USED FOR EDIT
                    "query_title": r["query_title"],
                    "session_id": r["session_id"],
                    "created_by": r["created_by"],
                    "created_at": r["created_at"],
                    "created_date": r["created_date"],
                    "latest_time": r["actual_created_at"],
                    "row_count": r["rows_effected"] or 0,
                    "query_time": r["query_time"] or "0",
                    "messages": []
                }

            # keep latest meta for list page
            if r["actual_created_at"] > query_map[root_id]["latest_time"]:
                query_map[root_id]["latest_time"] = r["actual_created_at"]
                query_map[root_id]["query_title"] = r["query_title"]
                query_map[root_id]["row_count"] = r["rows_effected"] or 0
                query_map[root_id]["query_time"] = r["query_time"] or "0"
                query_map[root_id]["created_at"] = r["created_at"]
                query_map[root_id]["created_date"] = r["created_date"]

            # full message history (for edit page)
            query_map[root_id]["messages"].append({
                "id": r["id"],
                "query": r["query"],
                "ai_response": r["ai_response"],
                "is_execute": r["is_execute"],
                "row_count": r["rows_effected"],
                "query_time": r["query_time"],
                "parent_query_id": r["parent_query_id"],
                "version_no": r["version_no"],
                "is_latest": r["is_latest"],
                "actual_created_at": r["actual_created_at"],
                "updated_by": r["updated_by"],
                "updated_at": r["updated_at"]
            })

        # =========================================
        # SORT BY LATEST ACTIVITY
        # =========================================
        sorted_queries = sorted(
            query_map.values(),
            key=lambda x: x["latest_time"],
            reverse=True
        )
        # cleanup + FIX MESSAGE ORDER
        for q in sorted_queries:
            q.pop("latest_time", None)

            # VERY IMPORTANT FIX
            q["messages"] = sorted(
                q["messages"],
                key=lambda m: m["actual_created_at"]   # ASC → old → new
            )

        # cleanup
        for q in sorted_queries:
            q.pop("latest_time", None)

        return build_response(
            True,
            "Query list loaded",
            200,
            {"queries": sorted_queries}
        )

    except Exception as e:
        return build_response(False, f"Server Error: {str(e)}", 500)
