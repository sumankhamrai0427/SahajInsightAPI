from flask import request
import os
from werkzeug.utils import secure_filename
from database.dbConnection import get_master_db
from helper.helperFunctions import build_response, allowed_logo
from dotenv import load_dotenv
load_dotenv()
MAX_LOGO_SIZE = 2 * 1024 * 1024  # 2MB
UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER")
BASE_URL = os.getenv("BASE_URL")

def update_company_logo_controller():
    master = None
    cursor = None
    try:
        company_id = request.form.get("company_id")
        logo_file = request.files.get("company_logo")

        if not company_id:
            return build_response(False, "company_id required", 400)

        if not logo_file:
            return build_response(False, "company_logo required", 400)

        if not allowed_logo(logo_file.filename):
            return build_response(False, "Only PNG/JPG allowed", 400)

        if len(logo_file.read()) > MAX_LOGO_SIZE:
            return build_response(False, "Logo must be < 2MB", 400)

        logo_file.seek(0)  # 🔥 VERY IMPORTANT

        master = get_master_db()
        cursor = master.cursor(dictionary=True, buffered=True)

        cursor.execute(
            "SELECT company_db_name FROM companies WHERE id=%s AND is_deleted=0",
            (company_id,)
        )
        company = cursor.fetchone()

        if not company:
            return build_response(False, "Company not found", 404)

        company_db_name = company["company_db_name"]

        company_folder = os.path.join(
            UPLOAD_FOLDER, "companies", company_db_name, "logo"
        )
        os.makedirs(company_folder, exist_ok=True)

        ext = secure_filename(logo_file.filename).rsplit(".", 1)[1].lower()
        filename = f"logo.{ext}"
        full_path = os.path.join(company_folder, filename)

        logo_file.save(full_path)

        logo_path = f"/uploads/companies/{company_db_name}/logo/{filename}"
        logo_url = f"{BASE_URL}{logo_path}"
        cursor.execute(
            "UPDATE companies SET company_logo=%s, updated_at=NOW() WHERE id=%s",
            (logo_path, company_id)
        )
        master.commit()

        cursor.close()
        cursor = None
        master.close()
        master = None

        return build_response(
            True,
            "Company logo updated successfully",
            200,
            data={
                "company_logo": logo_path,        # DB / internal use
                "company_logo_url": logo_url      # UI / frontend use
               }        
        )

    except Exception as e:
        return build_response(False, "Server error", 500, data={"error": str(e)})
    finally:
        if cursor is not None:
            try:
                cursor.close()
            except Exception:
                pass
        if master is not None:
            try:
                master.close()
            except Exception:
                pass
