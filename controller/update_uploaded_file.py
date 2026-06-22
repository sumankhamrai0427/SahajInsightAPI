from flask import request, g
import re
from helper.helperFunctions import build_response

def update_uploaded_file_controller():
    conn = None
    cursor = None
    try:
        data = request.get_json() or {}

        session_id = data.get("session_id")
        created_by = data.get("created_by")
        file_id = data.get("file_id")
        new_workspace_id = data.get("workspace_id")
        new_table_name = data.get("table_name")

        if not session_id or not created_by or not file_id:
            return build_response(
                False,
                "session_id, created_by & file_id are required",
                400
            )

        conn = g.company_db
        cursor = conn.cursor(dictionary=True)

        # 1. Fetch current file details
        cursor.execute("SELECT * FROM uploaded_files WHERE id = %s", (file_id,))
        file_record = cursor.fetchone()
        if not file_record:
            return build_response(False, "Uploaded file not found", 404)

        old_table_name = file_record.get("table_name")
        old_workspace_id = file_record.get("workspace_id")

        # 2. Validate workspace if it's changing
        if new_workspace_id is not None and int(new_workspace_id) != old_workspace_id:
            cursor.execute("SELECT id FROM workspaces WHERE id = %s", (new_workspace_id,))
            workspace_record = cursor.fetchone()
            if not workspace_record:
                return build_response(False, "Workspace not found", 404)

        # 3. Handle table rename if table_name is changing
        actual_new_table_name = old_table_name
        if new_table_name and new_table_name.strip() != old_table_name:
            actual_new_table_name = new_table_name.strip()
            # Validate table name pattern (alphanumeric and underscores only)
            if not re.match(r'^[a-zA-Z0-9_]+$', actual_new_table_name):
                return build_response(
                    False,
                    "Invalid table name. Only alphanumeric characters and underscores are allowed.",
                    400
                )

            # Check if new table name already exists in uploaded_files
            cursor.execute(
                "SELECT id FROM uploaded_files WHERE table_name = %s AND id != %s",
                (actual_new_table_name, file_id)
            )
            exists_record = cursor.fetchone()
            if exists_record:
                return build_response(False, f"Table name '{actual_new_table_name}' already exists in another file", 400)

            # Check if table actually exists in the database
            cursor.execute(
                "SELECT COUNT(*) as count FROM information_schema.tables WHERE table_schema = DATABASE() AND table_name = %s",
                (actual_new_table_name,)
            )
            table_exists_db = cursor.fetchone()
            if table_exists_db and table_exists_db['count'] > 0:
                return build_response(False, f"Database table '{actual_new_table_name}' already exists", 400)

            # If old table exists in database, rename it
            if old_table_name:
                cursor.execute(
                    "SELECT COUNT(*) as count FROM information_schema.tables WHERE table_schema = DATABASE() AND table_name = %s",
                    (old_table_name,)
                )
                old_table_exists_db = cursor.fetchone()
                if old_table_exists_db and old_table_exists_db['count'] > 0:
                    rename_sql = f"RENAME TABLE `{old_table_name}` TO `{actual_new_table_name}`"
                    cursor.execute(rename_sql)

        # 4. Perform update in uploaded_files
        update_fields = []
        update_params = []

        if new_workspace_id is not None:
            update_fields.append("workspace_id = %s")
            update_params.append(new_workspace_id)

        if actual_new_table_name != old_table_name:
            update_fields.append("table_name = %s")
            update_params.append(actual_new_table_name)

        if update_fields:
            update_params.append(file_id)
            update_sql = f"UPDATE uploaded_files SET {', '.join(update_fields)} WHERE id = %s"
            cursor.execute(update_sql, tuple(update_params))
            conn.commit()

        return build_response(True, "Uploaded file updated successfully", 200, {
            "file_id": file_id,
            "workspace_id": new_workspace_id if new_workspace_id is not None else old_workspace_id,
            "table_name": actual_new_table_name
        })

    except Exception as e:
        if conn:
            conn.rollback()
        return build_response(False, f"Update Error: {str(e)}", 500)

    finally:
        if cursor:
            cursor.close()
