import os
import json
from flask import Flask, request, g
from controller.get_file_status import get_file_status_controller
from database.dbConnection import get_company_db

app = Flask(__name__)

@app.route("/test", methods=["POST"])
def test():
    try:
        g.company_db = get_company_db("sahaj_cmp_ABCGEN001")
        return get_file_status_controller()
    except Exception as e:
        return {"error": str(e)}, 500

if __name__ == "__main__":
    app.run(port=5005)
