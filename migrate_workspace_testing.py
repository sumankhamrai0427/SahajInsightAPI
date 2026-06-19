from database.dbConnection import get_company_db

def migrate():
    db = get_company_db("sahaj_cmp_COMGEN002")
    c = db.cursor()
    print("Altering tables...")
    try:
        c.execute("""
        CREATE TABLE IF NOT EXISTS workspaces (
            id INT AUTO_INCREMENT PRIMARY KEY,
            workspace_name VARCHAR(255) NOT NULL,
            created_by VARCHAR(100),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        c.execute("""
        CREATE TABLE IF NOT EXISTS workspace_users (
            id INT AUTO_INCREMENT PRIMARY KEY,
            workspace_id INT NOT NULL,
            user_email VARCHAR(100) NOT NULL,
            assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE
        )
        """)
        try:
            c.execute("ALTER TABLE uploaded_files ADD COLUMN workspace_id INT")
        except Exception as e:
            print(f"Skipping uploaded_files: {e}")
            
        try:
            c.execute("ALTER TABLE query_history ADD COLUMN workspace_id INT")
        except Exception as e:
            print(f"Skipping query_history: {e}")
            
        # Re-run stored procedures creation script
        from controller.admin_company_register import get_master_db
        # We can't easily re-run just the SPs. I will just run them manually here.
        # Actually, let's just let the frontend test it. Wait, the SPs need to be updated in the DB!
        
        c.execute("DROP PROCEDURE IF EXISTS sp_get_uploaded_files_status")
        c.execute("""
    CREATE PROCEDURE sp_get_uploaded_files_status(
        IN p_created_by VARCHAR(100),
        IN p_session_id VARCHAR(100),
        IN p_workspace_id INT
    )
    BEGIN
        SELECT 
            uf.id AS file_id,
            uf.file_name,
            uf.table_name,
            uf.file_size_mb,
            uf.file_type,
            uf.last_inserted_rows as rows_effected,
            uf.total_columns,

            COALESCE(uf.table_extraction_status, 'pending') AS table_extraction_status,
            COALESCE(uf.column_extraction_status, 'pending') AS column_extraction_status,
            COALESCE(uf.data_insights_status, 'pending') AS data_insights_status,
			COALESCE(uf.data_insert_status, 'pending') AS data_insert_status,

            uf.insights,
        (
            SELECT COUNT(*)
            FROM query_history qh
            WHERE qh.session_id = uf.session_id
              AND qh.created_by = uf.created_by
              AND JSON_CONTAINS(qh.table_names, JSON_QUOTE(uf.table_name))
        ) AS connected_queries,

        (
            SELECT COUNT(*)
            FROM saved_reports sr
            JOIN query_history qh ON qh.id = sr.query_history_id
            WHERE qh.session_id = uf.session_id
              AND qh.created_by = uf.created_by
              AND JSON_CONTAINS(qh.table_names, JSON_QUOTE(uf.table_name))
        ) AS connected_reports,

        (
            SELECT JSON_ARRAYAGG(qh.query_title)
            FROM query_history qh
            WHERE qh.session_id = uf.session_id
              AND qh.created_by = uf.created_by
              AND JSON_CONTAINS(qh.table_names, JSON_QUOTE(uf.table_name))
        ) AS query_titles,

        (
            SELECT JSON_ARRAYAGG(sr.report_name)
            FROM saved_reports sr
            JOIN query_history qh ON qh.id = sr.query_history_id
            WHERE qh.session_id = uf.session_id
              AND qh.created_by = uf.created_by
              AND JSON_CONTAINS(qh.table_names, JSON_QUOTE(uf.table_name))
        ) AS report_names,

            TIME_FORMAT(uf.created_at, '%H:%i:%s') AS created_at,
            DATE_FORMAT(uf.created_at, '%d-%m-%Y') AS created_date,
            uf.updated_at

        FROM uploaded_files uf
        WHERE (p_workspace_id IS NOT NULL AND uf.workspace_id = p_workspace_id)
           OR (p_workspace_id IS NULL AND uf.created_by = p_created_by AND uf.session_id = p_session_id)
        ORDER BY  COALESCE(uf.updated_at, uf.created_at) DESC;
    END
        """)

        c.execute("DROP PROCEDURE IF EXISTS sp_insert_uploaded_file")
        c.execute("""
    CREATE PROCEDURE sp_insert_uploaded_file(
            IN p_session_id VARCHAR(100),
            IN p_workspace_id INT,
            IN p_file_name VARCHAR(255),
            IN p_table_name VARCHAR(255),
            IN p_file_size_mb VARCHAR(255),
            IN p_file_type VARCHAR(20),
            IN p_actual_rows INT,
            IN p_actual_columns INT,
            IN p_total_rows INT,
            IN p_total_columns INT,
            IN p_created_by VARCHAR(100),
            IN p_table_status VARCHAR(20),
            IN p_column_status VARCHAR(20),
            IN p_insights LONGTEXT,
            IN p_insights_status VARCHAR(20),
            IN p_data_insert_status VARCHAR(20),
            IN p_last_inserted_rows INT
        )
        BEGIN
            DECLARE v_file_id INT;

            INSERT INTO uploaded_files (
                session_id,
                workspace_id,
                file_name,
                table_name,
                file_size_mb,
                file_type,
                actual_rows,
                actual_columns,
                total_rows,
                total_columns,
                created_by,
                table_extraction_status,
                column_extraction_status,
                insights,
                data_insights_status,
                data_insert_status,
                last_inserted_rows
            )
            VALUES (
                p_session_id,
                p_workspace_id,
                p_file_name,
                p_table_name,
                p_file_size_mb,
                p_file_type,
                p_actual_rows,
                p_actual_columns,
                p_total_rows,
                p_total_columns,
                p_created_by,
                p_table_status,
                p_column_status,
                p_insights,
                p_insights_status,
                p_data_insert_status,
                p_last_inserted_rows
            );
            SET v_file_id = LAST_INSERT_ID();

            SELECT v_file_id AS file_id, 'CREATED' AS status_flag;
        END
        """)

        c.execute("DROP PROCEDURE IF EXISTS sp_save_query")
        c.execute("""
    CREATE PROCEDURE sp_save_query(
        IN p_session_id VARCHAR(100),
        IN p_workspace_id INT,
        IN p_created_by VARCHAR(100),
        IN p_query_title VARCHAR(150),

        IN p_message_query_id VARCHAR(150),
        IN p_user_query LONGTEXT,
        IN p_ai_response LONGTEXT,
        IN p_executable_sql LONGTEXT,
        IN p_table_names JSON,
        IN p_is_execute TINYINT(1),
        IN p_is_success TINYINT(1),
        IN p_row_count INT,
        IN p_query_time DECIMAL(10,3),

        IN p_mode VARCHAR(20),
        IN p_parent_query_id INT
    )
    BEGIN
        INSERT INTO query_history (
            session_id,
            workspace_id,
            created_by,
            query_title,
            message_query_id,
            user_query,
            ai_response,
            executable_sql,
            table_names,
            is_execute,
            is_success,
            row_count,
            query_time,
            mode,
            parent_query_id
        )
        VALUES (
            p_session_id,
            p_workspace_id,
            p_created_by,
            p_query_title,
            p_message_query_id,
            p_user_query,
            p_ai_response,
            p_executable_sql,
            p_table_names,
            p_is_execute,
            p_is_success,
            p_row_count,
            p_query_time,
            p_mode,
            p_parent_query_id
        );
        
        SELECT LAST_INSERT_ID() AS saved_id;
    END
        """)

        c.execute("DROP PROCEDURE IF EXISTS sp_get_query_details_by_user_session_id")
        c.execute("""
    CREATE PROCEDURE sp_get_query_details_by_user_session_id(
        IN p_created_by VARCHAR(100),
        IN p_session_id VARCHAR(100),
        IN p_workspace_id INT
    )
    BEGIN
         SELECT 
        q.id,
        q.query_title,
        q.user_query,
        q.ai_response,
        q.executable_sql,
        q.table_names,
        q.is_execute,
        q.is_success,
        q.row_count,
        q.query_time,
        q.mode,
        q.parent_query_id,
        q.created_at,
        q.updated_at
     FROM query_history q
    WHERE q.created_by = p_created_by
      AND (
          (p_workspace_id IS NOT NULL AND q.workspace_id = p_workspace_id)
          OR (p_workspace_id IS NULL AND q.session_id = p_session_id)
      )
      AND q.mode IN ('NEW','EDIT','CONTEXT')
    ORDER BY 
      q.created_at DESC;     
    END
        """)

        db.commit()
        print("Done!")
    except Exception as e:
        print(f"Error: {e}")
    finally:
        c.close()
        db.close()

if __name__ == "__main__":
    migrate()
