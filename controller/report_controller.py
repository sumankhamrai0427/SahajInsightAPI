
import json
from flask import request,g
from database.dbConnection import get_db_connection
from helper.helperFunctions import build_response,save_base64_image
import os 
from dotenv import load_dotenv
 
# ---------- Load Environment Variables ----------
load_dotenv() 
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
BASE_URL = os.getenv("BASE_URL")
 
 

def save_report_controller():
    try:
        data = request.get_json()

        session_id = data.get("session_id")
        user_id = data.get("created_by")
        report_id = data.get("report_id")
        report_name = data.get("report_name")
        query_history_id = data.get("query_history_id")
        report_config = data.get("report_config")
        if not all([session_id, user_id, report_id, report_name, query_history_id,report_config]):
            return build_response(False, "Missing required fields", 400)
     
        # -----------------------------
        # COMPANY DB MUST ALREADY EXIST
        # (set by attach_company_db)
        # -----------------------------
        if not hasattr(g, "company_db"):
            return build_response(False, "Invalid session", 401)

        conn = g.company_db
        # cur = conn.cursor()
        cur = conn.cursor(dictionary=True)
        # Validate session + user
        cur.execute("""
            SELECT 1 FROM users
            WHERE session_id=%s AND user_id=%s
        """, (session_id, user_id))
        if not cur.fetchone():
            return build_response(False, "Invalid session or user", 401)

        # Fetch row_affected
        cur.execute("""
            SELECT row_count FROM query_history WHERE id=%s
        """, (query_history_id,))
        row = cur.fetchone()
        if not row:
            return build_response(False, "Invalid query_history_id", 404)

        rows_effected = row["row_count"]


        # Call SP (save or update)
        args = [
            report_id,
            session_id,
            user_id,
            report_name,
            query_history_id,
            rows_effected,
            json.dumps(report_config),
            None   # OUT param
        ]

        result = cur.callproc("sp_save_or_update_report", args)
        # action = result[-1]   # INSERT / UPDATE / EXISTS
        cur.execute("SELECT @_sp_save_or_update_report_6 AS action")
        action = cur.fetchone()["action"]
        chart_images = data.get("chart_images", [])

        if chart_images:
            report_folder = os.path.join(
                UPLOAD_FOLDER,      # uploads
                "reports",
                report_id
            )
            os.makedirs(report_folder, exist_ok=True)

            saved_images = []

            for img in chart_images:
                filename = f"{img['type']}_{img['order']}.png"
                filepath = os.path.join(report_folder, filename)

                save_base64_image(img["image_base64"], filepath)

                saved_images.append({
                    "chart_id": img["chart_id"],
                    "type": img["type"],
                    "order": img["order"],
                    "path": f"/uploads/reports/{report_id}/{filename}"
                })

            #  existing report_config JSON 
            report_config = (
                report_config
                if isinstance(report_config, dict)
                else json.loads(report_config)
            )

            #  image info JSON 
            report_config["chart_images"] = saved_images

            #  DB update
            cur.execute("""
                UPDATE saved_reports
                SET report_config=%s
                WHERE report_id=%s
                AND session_id=%s
                AND user_id=%s
            """, (
                json.dumps(report_config),
                report_id,
                session_id,
                user_id
            ))

          

        conn.commit()
        cur.close()
      

        if action == "EXISTS":
            return build_response(True, "Report already exists", 200)

        if action == "UPDATE":
            return build_response(True, "Report updated successfully", 200)

        return build_response(True, "Report saved successfully", 200)

    except Exception as e:
        return build_response(False, "Server Error", 500, {"error": str(e)})


def report_list_controller():
    try:
        data = request.get_json() or {}
        session_id = data.get("session_id")
        user_id = data.get("created_by")

        if not session_id or not user_id:
            return build_response(False, "session_id & user_id required", 400)
        
        # -----------------------------
        # COMPANY DB MUST ALREADY EXIST
        # (set by attach_company_db)
        # -----------------------------
        if not hasattr(g, "company_db"):
            return build_response(False, "Invalid session", 401)

        conn = g.company_db
        cur = conn.cursor(dictionary=True)

        # Validate session + user
        cur.execute("""
            SELECT 1 FROM users
            WHERE session_id=%s AND user_id=%s
        """, (session_id, user_id))
        if not cur.fetchone():
            return build_response(False, "Invalid session or user", 401)

        #  V2 SP call
        cur.callproc("sp_get_report_list", [session_id, user_id])

        rows = []
        for res in cur.stored_results():
            rows = res.fetchall()

        result = []
        for r in rows:
            report_config = (
                    r["report_config"]
                    if isinstance(r["report_config"], dict)
                    else json.loads(r["report_config"])
                )

                #  add full url for chart images
            if "chart_images" in report_config:
                    base_url = BASE_URL
                    # base_url = request.host_url.rstrip("/")   # http://127.0.0.1:3008
                    for img in report_config["chart_images"]:
                        img["url"] = f"{base_url}{img['path']}"   

            result.append({
                # ===== SAME AS OLD =====
                "report_id": r["report_id"],
                "report_name": r["report_name"],
                "row_affected": r["row_affected"],
                "report_config": report_config,
                "group_by": [],
                "created_at": r["created_at"],
                "actual_created_at": r["actual_created_at"],
                "actual_created_date": r["actual_created_date"],
                "actual_saved_at": r["actual_saved_at"],
                "actual_saved_date": r["actual_saved_date"],
                # ADDITION (non-breaking)
                "query_history_id": r["query_history_id"],

                # ===== SAME AS OLD =====
                "query": {
                    "query_id": r["query_history_id"],   #  map here
                    "query_name": r["query_title"],
                    "ai_responce": r["ai_response"]
                }
            })

        cur.close()
      

        #  SAME response wrapper as OLD
        return build_response(True, "Report list fetched successfully", 200, {
            "Report list": result
        })

    except Exception as e:
        return build_response(False, "Server Error", 500, {"error": str(e)})
