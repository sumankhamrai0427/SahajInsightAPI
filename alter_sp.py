import os
from database.dbConnection import get_master_db

def main():
    db = get_master_db()
    c = db.cursor(dictionary=True)
    c.execute("SELECT company_db_name FROM companies")
    companies = c.fetchall()
    
    for row in companies:
        company_db = row['company_db_name']
        print(f"Updating SP in {company_db}...")
        
        c.execute(f"DROP PROCEDURE IF EXISTS `{company_db}`.sp_insert_uploaded_file")
        
        sp = f"""
        CREATE PROCEDURE `{company_db}`.`sp_insert_uploaded_file`(
            IN p_session_id VARCHAR(100),
            IN p_file_name VARCHAR(255),
            IN p_table_name VARCHAR(255),
            IN p_file_size_mb VARCHAR(255),
            IN p_file_type VARCHAR(20),
            IN p_actual_rows INT,
            IN p_actual_columns INT,
            IN p_total_rows INT,
            IN p_total_columns INT,
            IN p_created_by VARCHAR(100),
            IN p_workspace_id VARCHAR(100),
            IN p_table_status VARCHAR(20),
            IN p_column_status VARCHAR(20),
            IN p_insights LONGTEXT,
            IN p_insights_status VARCHAR(20),
            IN p_data_insert_status VARCHAR(20),
            IN p_last_inserted_rows INT
        )
        proc_main: BEGIN

            DECLARE v_pending_id INT DEFAULT NULL;

            SELECT id
            INTO v_pending_id
            FROM uploaded_files
            WHERE session_id COLLATE utf8mb4_unicode_ci = p_session_id COLLATE utf8mb4_unicode_ci
            AND table_name COLLATE utf8mb4_unicode_ci = p_table_name COLLATE utf8mb4_unicode_ci
            AND data_insert_status = 'pending'
            ORDER BY created_at ASC
            LIMIT 1;

            IF v_pending_id IS NOT NULL AND p_data_insert_status = 'done' THEN

                UPDATE uploaded_files
                SET
                    file_name = p_file_name,
                    file_size_mb = p_file_size_mb,
                    actual_rows = p_actual_rows,
                    actual_columns = p_actual_columns,
                    total_rows = p_total_rows,
                    total_columns = p_total_columns,
                    last_inserted_rows = p_last_inserted_rows,
                    insights = p_insights,
                    data_insights_status = p_insights_status,
                    data_insert_status = 'done',
                    workspace_id = p_workspace_id,
                    updated_at = NOW()
                WHERE id = v_pending_id;

                SELECT v_pending_id AS file_id, 'UPDATED' AS status_flag;
                LEAVE proc_main;
            END IF;

            INSERT INTO uploaded_files (
                session_id,
                file_name,
                table_name,
                file_size_mb,
                file_type,
                actual_rows,
                actual_columns,
                total_rows,
                total_columns,
                last_inserted_rows,
                created_by,
                workspace_id,
                created_at,
                table_extraction_status,
                column_extraction_status,
                insights,
                data_insights_status,
                data_insert_status
            )
            VALUES (
                p_session_id,
                p_file_name,
                p_table_name,
                p_file_size_mb,
                p_file_type,
                p_actual_rows,
                p_actual_columns,
                p_total_rows,
                p_total_columns,
                p_last_inserted_rows,
                p_created_by,
                p_workspace_id,
                NOW(),
                p_table_status,
                p_column_status,
                p_insights,
                p_insights_status,
                p_data_insert_status
            );

            SELECT LAST_INSERT_ID() AS file_id, 'NEW' AS status_flag;
        END
        """
        c.execute(sp)
    
    db.commit()
    c.close()
    db.close()
    print("Done")

if __name__ == '__main__':
    main()
