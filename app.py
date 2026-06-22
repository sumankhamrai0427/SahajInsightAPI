import os
from flask import Flask, request, g, send_from_directory
from flask_cors import CORS
from controller import company_get_users
from controller.company_logo_controller import update_company_logo_controller
from controller.company_user_register import company_user_register_controller
from controller.get_company_code_dropdown import get_company_code_dropdown_controller
from controller.get_file_status import get_file_status_controller
from controller.get_full_table_info import get_full_table_info_controller
from controller.get_dashboard_data import get_dashboard_data_controller
from controller.sql_ai_executor import (
    chat_endpoint_controller,
    execute_sql_endpoint_controller,
)
from controller.query_save import query_save_controller
from controller.get_saved_query_response import get_saved_query_response_controller
from controller.delete_upload_file import delete_uploaded_file_controller
from controller.upload_file_new import (
    upload_and_insights_new_controller,
    get_upload_progress_controller as upload_progress_ctrl,
)
from controller.report_controller import save_report_controller, report_list_controller
from controller.admin_company_register import admin_company_register_controller, get_country_options
from controller.admin_company_admin_register import (
    admin_company_admin_register_controller,
)
from middleware.dbContext import attach_company_db
from controller.superadmin_login import superadmin_login_controller
from controller.company_login import company_login_controller
from controller.get_all_companies import get_all_companies_controller
from controller.admin_company_delete import delete_company
from controller.ai_chart_controller import modify_chart_controller
from controller.get_all_company_admins import get_all_company_admins_controller
from controller.company_get_users import get_company_users_controller
from controller.contact_handel import handle_contact_controller
from controller.llm_web_search import llm_web_search_controller
from controller.summarize_sources import summarize_sources_controller
from controller.update_uploaded_file import update_uploaded_file_controller



from controller.seo_api import create_seo_entry_controller,update_seo_entry_controller,delete_seo_entry_controller,get_seo_data_controller,get_seo_by_path_controller
from controller.rag_controller import (
    rag_ingest_web_search_controller,
    rag_ingest_csv_controller,
    rag_ingest_selected_controller,
    rag_chat_controller,
    save_rag_chat_controller,
    get_rag_chat_history_controller
)
from controller.unified_chat_controller import unified_chat_controller
from controller.workspace_controller import (
    create_workspace_controller,
    list_workspaces_controller,
    assign_user_to_workspace_controller,
    get_assigned_users_controller,
    get_user_workspaces_controller,
    get_all_users_for_workspace_controller
)
# app = Flask(__name__,
#     static_url_path="/uploads",
#     static_folder=os.getenv("UPLOAD_FOLDER"))

app = Flask(__name__)
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_ROOT = os.path.join(BASE_DIR, "uploads")
CORS(app)


@app.before_request
def before_request():
    return attach_company_db()


@app.route("/")
def hello_world():
    return "Hello, World!"


@app.route("/company_user_register", methods=["POST"])
def company_user_register_route():
    return company_user_register_controller()


@app.route("/superadmin/login", methods=["POST"])
def superadmin_login():
    return superadmin_login_controller()


@app.route("/company/login", methods=["POST"])
def company_login():
    return company_login_controller()


@app.route("/get_file_status", methods=["POST"])
def get_file_status_route():
    return get_file_status_controller()


@app.route("/upload_files_new", methods=["POST"])
def upload_and_insights_new_route():
    return upload_and_insights_new_controller()


@app.route("/get_full_table_info", methods=["POST"])
def get_full_table_info_route():
    return get_full_table_info_controller()


@app.route("/get_dashboard_data", methods=["POST"])
def get_dashboard_data_route():
    return get_dashboard_data_controller()


@app.route("/chat/unified", methods=["POST"])
def unified_chat_route():
    return unified_chat_controller()

@app.route("/chat_ai", methods=["POST"])
def chat_endpoint_route():
    return chat_endpoint_controller()


@app.route("/llm_web_search", methods=["POST"])
def llm_web_search_route():
    return llm_web_search_controller()


@app.route("/summarize_sources", methods=["POST"])
def summarize_sources_route():
    return summarize_sources_controller()



@app.route("/rag/ingest/web_search", methods=["POST"])
def rag_ingest_web_search_route():
    return rag_ingest_web_search_controller()

@app.route("/rag/ingest/csv", methods=["POST"])
def rag_ingest_csv_route():
    return rag_ingest_csv_controller()

@app.route("/rag/ingest/selected", methods=["POST"])
def rag_ingest_selected_route():
    return rag_ingest_selected_controller()

@app.route("/rag/chat", methods=["POST"])
def rag_chat_route():
    return rag_chat_controller()

@app.route("/rag/chat/save", methods=["POST"])
def save_rag_chat_route():
    from controller.rag_controller import save_rag_chat_controller
    return save_rag_chat_controller()

@app.route("/rag/chat/history", methods=["POST"])
def get_rag_chat_history_route():
    from controller.rag_controller import get_rag_chat_history_controller
    return get_rag_chat_history_controller()


@app.route("/admin/workspace/create", methods=["POST"])
def create_workspace_route():
    return create_workspace_controller()

@app.route("/admin/workspace/list", methods=["POST"])
def list_workspaces_route():
    return list_workspaces_controller()

@app.route("/admin/workspace/assign_user", methods=["POST"])
def assign_user_to_workspace_route():
    return assign_user_to_workspace_controller()

@app.route("/admin/workspace/assigned_users", methods=["POST"])
def get_assigned_users_route():
    return get_assigned_users_controller()

@app.route("/user/my_workspaces", methods=["POST"])
def get_user_workspaces_route():
    return get_user_workspaces_controller()

@app.route("/admin/workspace/all_users", methods=["POST"])
def get_all_users_for_workspace_route():
    return get_all_users_for_workspace_controller()


@app.route("/execute_sql", methods=["POST"])
def execute_sql_endpoint_route():
    return execute_sql_endpoint_controller()


@app.route("/query_save", methods=["POST"])
def query_save_route():
    return query_save_controller()


@app.route("/get_saved_query_response", methods=["POST"])
def get_saved_query_response_route():
    return get_saved_query_response_controller()


@app.route("/delete_uploaded_file", methods=["POST"])
def delete_uploaded_file_route():
    return delete_uploaded_file_controller()


@app.route("/update_uploaded_file", methods=["POST"])
def update_uploaded_file_route():
    return update_uploaded_file_controller()


@app.route("/report_save", methods=["POST"])
def report_save_route():
    return save_report_controller()


@app.route("/report_list", methods=["POST"])
def report_list_route():
    return report_list_controller()


@app.route("/admin/company_register", methods=["POST"])
def admin_company_register_route():
    return admin_company_register_controller()


@app.route("/admin/company/admin_register", methods=["POST"])
def admin_company_admin_register_route():
    return admin_company_admin_register_controller()


@app.route("/uploads/<path:filename>")
def serve_uploads(filename):
    return send_from_directory(UPLOAD_ROOT, filename)


@app.route("/get_upload_progress", methods=["POST"])
def get_upload_progress_route():
    return upload_progress_ctrl()


@app.route("/admin/get_companies", methods=["GET"])
def get_all_companies_route():
    return get_all_companies_controller()

@app.route("/admin/company_delete", methods=["POST"])
def company_delete_route():
    return delete_company()

@app.route("/modify_chart", methods=["POST"])
def modify_chart_route():
    return modify_chart_controller()

@app.route("/admin/get_all_company_admins", methods=["GET"])
def get_all_company_admins_route():
    return get_all_company_admins_controller()

@app.route("/admin/company_code_dropdown", methods=["GET"])
def company_code_dropdown():
    return get_company_code_dropdown_controller()

@app.route("/admin/company_get_users", methods=["POST"])
def company_get_user_route():
    return get_company_users_controller()

@app.route("/contact", methods=["POST"])
def contact():
    return handle_contact_controller()


@app.route('/get_country_options', methods=['GET'])
def country():
    return get_country_options()

@app.route("/admin/company/logo", methods=["POST"])
def update_company_logo():
    return update_company_logo_controller()

@app.route("/admin/create_seo", methods=["POST"])
def create_seo_route():
    return create_seo_entry_controller()

@app.route("/admin/update_seo", methods=["POST"])
def update_seo_route():
    return update_seo_entry_controller()


@app.route("/admin/delete_seo", methods=["POST"])
def delete_seo_route():
    return delete_seo_entry_controller()

@app.route("/admin/get_seo_list", methods=["GET"])
def get_seo_route():
    return get_seo_data_controller()

@app.route("/admin/get_seo_by_path", methods=["GET"])
def get_seo_by_path_route():
    return get_seo_by_path_controller()

@app.route("/logo")
def logo():
    return send_from_directory("logo", "projectIcon.png")


# Run the Flask Server
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=3008, debug=True,)
