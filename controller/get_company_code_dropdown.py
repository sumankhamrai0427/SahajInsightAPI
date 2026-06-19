from database.dbConnection import get_master_db
from helper.helperFunctions import build_response


def get_company_code_dropdown_controller():
    try:
        master = get_master_db()
        cursor = master.cursor(dictionary=True)

        cursor.execute("""
            SELECT 
                company_name,
                company_code
            FROM companies
            WHERE is_active = 1
              AND is_deleted = 0
            ORDER BY company_name ASC
        """)

        rows = cursor.fetchall()

        dropdown = [
            {
                "label": f"{row['company_name']} - {row['company_code']}",
                "value": row["company_code"]
            }
            for row in rows
        ]

        cursor.close()
        master.close()

        return build_response(
            True,
            "Company code dropdown fetched successfully",
            200,
            data=dropdown
        )

    except Exception as e:
        return build_response(
            False,
            "Server error",
            500,
            data={"error": str(e)}
        )
