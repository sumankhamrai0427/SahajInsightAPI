from flask import request
from database.dbConnection import get_db_connection
from helper.helperFunctions import build_response, format_dates_in_rows

def get_full_table_info_controller():
    try:
        body = request.get_json()
        created_by = body.get("created_by")
        session_id = body.get("session_id")

        if not created_by or not session_id:
            return build_response(False, "created_by & session_id required", 400)

        db = get_db_connection()
        cursor = db.cursor(dictionary=True)
        #  VALIDATE SESSION ID & created_by
        # -----------------------------------
        cursor.execute(
            "SELECT user_id, session_id FROM users WHERE session_id = %s AND user_id = %s LIMIT 1",
            (session_id, created_by)
        )
        session_row = cursor.fetchone()

        if not session_row:
            cursor.close()
            db.close()
            return build_response(
                False,
                "Invalid session_id or created_by",
                400
                # {"status": "failed"}
            )

        # CALL STORED PROCEDURE
        cursor.callproc("sp_get_full_table_info", [created_by, session_id])
        results = list(cursor.stored_results())

        # ----------------------
        # TABLE LIST
        # ----------------------
        table_list = results[0].fetchall()  # [{label,value}, ...]

        # ----------------------
        # COLUMN METADATA
        # ----------------------
        col_meta_list = results[1].fetchall()

        # group by table
        column_map = {}
        for c in col_meta_list:
            tbl = c["table_name"]
            if tbl not in column_map:
                column_map[tbl] = []

            column_map[tbl].append({
                "column_id": c["column_id"],
                "column_name": c["COLUMN_NAME"],
                "data_type": c["DATA_TYPE"]
            })

        # ----------------------
        # INSIGHTS
        # ----------------------
        insights_list = results[2].fetchall()
        insights_map = {i["table_name"]: i["insights"] for i in insights_list}

        # ----------------------
        # FETCH TABLE DATA SEPARATELY
        # ----------------------
        table_data_map = {}
        for t in table_list:
            tbl = t["value"]

            c2 = db.cursor(dictionary=True)
            # c2.execute(f"SELECT * FROM `{tbl}`")
            c2.execute(f"SELECT * FROM `{tbl}` LIMIT 500")
            rows = c2.fetchall()
            rows = format_dates_in_rows(rows)
            table_data_map[tbl] = rows
            # table_data_map[tbl] = c2.fetchall()
            c2.close()

        cursor.close()
        db.close()

        # ----------------------
        # MERGE EVERYTHING IN A SINGLE CLEAN OBJECT
        # ----------------------
        details = {}

        for t in table_list:
            tbl = t["value"]

            details[tbl] = {
                "columns": column_map.get(tbl, []),
                "insights": insights_map.get(tbl),
                "data": table_data_map.get(tbl, [])
            }

        # FINAL RESPONSE
        final_output = {
            "tables_dropdown": table_list,   # for dropdown
            "details": details      # table_name → metadata map
        }

        return build_response(True, "Full table info fetched", 200, final_output)

    except Exception as e:
        return build_response(False, "Server Error", 500, {"error": str(e)})