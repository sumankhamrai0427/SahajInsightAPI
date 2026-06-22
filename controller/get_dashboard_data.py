from flask import request,g
from helper.helperFunctions import build_response
from datetime import datetime

def generate_query_trend_insights(trend_data, avg_time, success_rate):
    insights = []
    
    if not trend_data:
        insights.append("No query activity recorded yet. Start querying to see AI insights.")
        return insights
        
    queries = [d.get("total_queries", 0) for d in trend_data]
    dates = []
    for d in trend_data:
        dt = d.get("query_date")
        if isinstance(dt, str):
            try:
                dates.append(datetime.strptime(dt, "%Y-%m-%d"))
            except ValueError:
                dates.append(dt)
        else:
            dates.append(dt)
            
    total_queries = sum(queries)
    if total_queries == 0:
        insights.append("No active database queries detected in the trend window.")
        return insights

    # 1. Peak Day Insight
    max_queries = max(queries)
    max_idx = queries.index(max_queries)
    peak_date = dates[max_idx]
    peak_date_str = peak_date.strftime("%A, %d %B") if isinstance(peak_date, datetime) else str(peak_date)
    insights.append(f"Highest database usage reached **{max_queries} queries** on **{peak_date_str}**.")

    # 2. Trend & Velocity Insight
    if len(queries) >= 2:
        recent_queries = queries[-1]
        prev_average = sum(queries[:-1]) / len(queries[:-1])
        if prev_average > 0:
            change_pct = ((recent_queries - prev_average) / prev_average) * 100
            if change_pct > 15:
                insights.append(f"Query volume is up by **{change_pct:.1f}%** compared to the weekly average.")
            elif change_pct < -15:
                insights.append(f"Query volume decreased by **{abs(change_pct):.1f}%** compared to the weekly average.")
            else:
                insights.append("Database query rate remains stable and balanced within the normal range.")
    
    # 3. Anomaly Detection
    avg_queries = total_queries / len(queries)
    for q, d in zip(queries, dates):
        if q > avg_queries * 2 and q > 5:
            d_str = d.strftime("%d %B") if isinstance(d, datetime) else str(d)
            insights.append(f"Unusual query spike (**{q} queries**) detected on **{d_str}**; check for automated tasks.")
            break

    # 4. Performance & Bottleneck Insight
    try:
        avg_t = float(avg_time) if avg_time is not None else 0.0
    except ValueError:
        avg_t = 0.0

    try:
        succ_r = float(success_rate) if success_rate is not None else 100.0
    except ValueError:
        succ_r = 100.0

    if avg_t > 1.5:
        insights.append("Avg response time is high (**{:.2f}s**). Adding query indexes is recommended.".format(avg_t))
    else:
        insights.append("Queries are executing fast (avg **{:.2f}s**). Latency is optimal.".format(avg_t))

    if succ_r < 90.0:
        insights.append("Success rate is low (**{:.1f}%**). Review query error history for schema mismatches.".format(succ_r))
    else:
        insights.append("Excellent query health with a **{:.1f}%** execution success rate.".format(succ_r))

    return insights


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

        # Generate query activity trend insights
        dashboard_data["query_trend_insights"] = generate_query_trend_insights(
            dashboard_data["query_activity_trend"],
            dashboard_data["avg_query_time"],
            dashboard_data["query_success_rate"]
        )

        return build_response(True, "Dashboard data retrieved", 200, dashboard_data)

    except Exception as e:
        return build_response(
            False,
            "Failed to retrieve dashboard data",
            500,
            {"error": str(e)}
        )
