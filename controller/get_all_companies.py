from database.dbConnection import get_master_db
from helper.helperFunctions import build_response

def get_all_companies_controller():
    try:
        master = get_master_db()
        cursor = master.cursor(dictionary=True)

        cursor.callproc("sp_get_all_companies")

        data = []
        for result in cursor.stored_results():
            data = result.fetchall()

        cursor.close()
        master.close()

        #  DIRECT DATA RETURN (NO EXTRA OBJECT)
        return build_response(
            True,
            "Company list fetched successfully",
            200,
            data=data
        )

    except Exception as e:
        return build_response(
            False,
            "Failed to fetch companies",
            500,
            data=str(e)
        )
