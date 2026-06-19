from flask import request, jsonify
from database.dbConnection import get_master_db


# --- 1. INSERT (Create) ---
def create_seo_entry_controller():
    data = request.get_json()
    page_path = data.get('page_path')
    keyword = data.get('target_keyword')
    title = data.get('seo_title')
    desc = data.get('meta_description')


    if not keyword:
        return jsonify({"error": "target_keyword is required"}), 400


    # 3. FIX: Call the function, not the config dict
    conn = get_master_db()
    
    if conn is None:
        return jsonify({"error": "Database connection failed"}), 500


    try:
        cursor = conn.cursor()
        query = "INSERT INTO seo_metadata (page_path,target_keyword, seo_title, meta_description) VALUES (%s, %s, %s, %s)"
        cursor.execute(query, (page_path, keyword, title, desc))
        conn.commit()
        new_id = cursor.lastrowid
        return jsonify({"success": True, "message": "SEO data added", "id": new_id}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    finally:
        try:
            cursor.close()
            conn.close()
        except Exception:
            pass




# --- 2. GET (Read) ---
def get_seo_data_controller(seo_id=None):
    conn = get_master_db()
    if conn is None:
        return jsonify({"isSuccess": False, "message": "Database connection failed"}), 500

    try:
        cursor = conn.cursor(dictionary=True)  #  IMPORTANT

        if seo_id:
            query = """
                SELECT id, page_path, seo_title, target_keyword, meta_description
                FROM seo_metadata
                WHERE id = %s
            """
            cursor.execute(query, (seo_id,))
            result = cursor.fetchone()

            if not result:
                return jsonify({"isSuccess": False, "message": "Not found"}), 404

            return jsonify({"isSuccess": True, "data": result}), 200

        else:
            query = """
                SELECT id, page_path, seo_title, target_keyword, meta_description
                FROM seo_metadata
                ORDER BY id DESC
            """
            cursor.execute(query)
            result = cursor.fetchall()

            return jsonify({"isSuccess": True, "data": result}), 200

    except Exception as e:
        return jsonify({"isSuccess": False, "message": str(e)}), 500

    finally:
        cursor.close()
        conn.close()


# --- 3. UPDATE ---
def update_seo_entry_controller():
    data = request.get_json()

    seo_id = data.get("id")
    page_path = data.get("page_path")
    keyword = data.get("target_keyword")
    title = data.get("seo_title")
    desc = data.get("meta_description")

    #  Validation
    if not seo_id:
        return jsonify({
            "isSuccess": False,
            "message": "SEO id is required"
        }), 400

    if not page_path or not keyword or not title or not desc:
        return jsonify({
            "isSuccess": False,
            "message": "All fields are required"
        }), 400

    conn = get_master_db()
    if conn is None:
        return jsonify({
            "isSuccess": False,
            "message": "Database connection failed"
        }), 500

    try:
        cursor = conn.cursor(dictionary=True)

        #  Check record exists
        cursor.execute(
            "SELECT id FROM seo_metadata WHERE id = %s",
            (seo_id,)
        )
        if not cursor.fetchone():
            return jsonify({
                "isSuccess": False,
                "message": "SEO entry not found"
            }), 404

        #  Update
        cursor.execute(
            """
            UPDATE seo_metadata
            SET
                page_path = %s,
                target_keyword = %s,
                seo_title = %s,
                meta_description = %s
            WHERE id = %s
            """,
            (page_path, keyword, title, desc, seo_id)
        )
        conn.commit()

        return jsonify({
            "isSuccess": True,
            "message": "SEO updated successfully"
        }), 200

    except Exception as e:
        return jsonify({
            "isSuccess": False,
            "message": str(e)
        }), 500

    finally:
        cursor.close()
        conn.close()



# --- 4. DELETE ---
def delete_seo_entry_controller():
    data = request.get_json()
    seo_id = data.get("id")

    if not seo_id:
        return jsonify({
            "isSuccess": False,
            "message": "SEO id is required"
        }), 400

    conn = get_master_db()
    if conn is None:
        return jsonify({
            "isSuccess": False,
            "message": "Database connection failed"
        }), 500

    try:
        cursor = conn.cursor(dictionary=True)

        #  Check exists
        cursor.execute(
            "SELECT id FROM seo_metadata WHERE id = %s",
            (seo_id,)
        )
        if not cursor.fetchone():
            return jsonify({
                "isSuccess": False,
                "message": "SEO entry not found"
            }), 404

        #  Delete
        cursor.execute(
            "DELETE FROM seo_metadata WHERE id = %s",
            (seo_id,)
        )
        conn.commit()

        return jsonify({
            "isSuccess": True,
            "message": "SEO deleted successfully"
        }), 200

    except Exception as e:
        return jsonify({
            "isSuccess": False,
            "message": str(e)
        }), 500

    finally:
        cursor.close()
        conn.close()



def get_seo_by_path_controller():
    page_path = request.args.get("path")

    if not page_path:
        return jsonify({"isSuccess": False, "message": "path required"}), 400

    conn = get_master_db()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
      SELECT seo_title, meta_description, target_keyword, page_path
      FROM seo_metadata
      WHERE page_path = %s
      LIMIT 1
    """, (page_path,))

    data = cursor.fetchone()

    cursor.close()
    conn.close()

    return jsonify({
        "isSuccess": True,
        "data": data  # may be null
    })
