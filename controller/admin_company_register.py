from flask import request
import mysql.connector
import os
from database.dbConnection import get_master_db, get_company_db
from helper.helperFunctions import build_response, allowed_logo
from datetime import datetime
import re
from werkzeug.utils import secure_filename




MAX_LOGO_SIZE = 2 * 1024 * 1024  # 2MB



def generate_company_code(company_name, cursor):
    clean = re.sub(r"[^a-zA-Z ]", "", company_name).upper()
    words = clean.split()


    prefix = words[0][:3]


    domain_map = {
        "RETAIL": "RTL",
        "TECH": "TEC",
        "TECHNOLOGY": "TEC",
        "SOLUTIONS": "SOL",
        "SERVICES": "SRV",
    }


    domain = "GEN"
    for w in words:
        if w in domain_map:
            domain = domain_map[w]
            break


    base_code = f"{prefix}{domain}"


    cursor.execute(
        """
        SELECT company_code
        FROM companies
        WHERE company_code LIKE %s
        ORDER BY id DESC
        LIMIT 1
    """,
        (f"{base_code}%",),
    )


    last = cursor.fetchone()


    seq = int(last["company_code"][-3:]) + 1 if last else 1


    return f"{base_code}{str(seq).zfill(3)}"



# ==========================================================
# ENV CONFIG
# ==========================================================
MASTER_DB_HOST = os.getenv("DB_HOST")
MASTER_DB_USER = os.getenv("DB_USER")
MASTER_DB_PASS = os.getenv("DB_PASSWORD")
UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER")
DB_CHARSET = os.getenv("DB_DEFAULT_CHARSET", "utf8mb4")
DB_ENGINE = os.getenv("DB_ENGINE", "InnoDB")



# ==========================================================
# CREATE ALL STORED PROCEDURES INSIDE COMPANY DB
# ==========================================================
def create_stored_procedures(db_name):
    conn = get_company_db(db_name)
    c = conn.cursor()


    c.execute(f"USE `{db_name}`")


    # =====================================================
    # sp_delete_uploaded_file
    # =====================================================
    c.execute("DROP PROCEDURE IF EXISTS sp_delete_uploaded_file")
    c.execute(
        """
    CREATE PROCEDURE sp_delete_uploaded_file(
    IN p_session_id VARCHAR(100),
    IN p_created_by VARCHAR(100),
    IN p_file_name VARCHAR(255)
)
proc_block:
BEGIN
    DECLARE v_table_name VARCHAR(255);
    DECLARE v_user_exists INT DEFAULT 0;
    DECLARE v_table_exists INT DEFAULT 0;
    DECLARE v_query_dep INT DEFAULT 0;
    DECLARE v_report_dep INT DEFAULT 0;


    /* --------------------------------
       Validate session + user
    -------------------------------- */
    SELECT COUNT(*) INTO v_user_exists
    FROM users
    WHERE user_id = p_created_by
      AND session_id = p_session_id;


    IF v_user_exists = 0 THEN
        SELECT 'Invalid session_id or created_by' AS status;
        LEAVE proc_block;
    END IF;


    /* --------------------------------
       Resolve table_name
    -------------------------------- */
    SELECT table_name
    INTO v_table_name
    FROM uploaded_files
    WHERE session_id = p_session_id
      AND created_by = p_created_by
      AND file_name = p_file_name
    LIMIT 1;


    IF v_table_name IS NULL THEN
        SELECT 'No file metadata found' AS status;
        LEAVE proc_block;
    END IF;


    /* --------------------------------
       QUERY dependency count
    -------------------------------- */
    SELECT COUNT(*) INTO v_query_dep
    FROM query_history
    WHERE session_id = p_session_id
      AND created_by = p_created_by
      AND table_names IS NOT NULL
      AND JSON_CONTAINS(table_names, JSON_QUOTE(v_table_name))
      AND is_execute = 1;


    /* --------------------------------
       REPORT dependency count
    -------------------------------- */
    SELECT COUNT(*) INTO v_report_dep
    FROM saved_reports sr
    JOIN query_history q ON q.id = sr.query_history_id
    WHERE sr.session_id = p_session_id
      AND sr.user_id = p_created_by
      AND q.table_names IS NOT NULL
      AND JSON_CONTAINS(q.table_names, JSON_QUOTE(v_table_name));


    /* --------------------------------
       COMBINED DEPENDENCY HANDLING
    -------------------------------- */
    IF v_query_dep > 0 OR v_report_dep > 0 THEN


        /* Result set 1 → status */
        SELECT CONCAT(
            'Table "', v_table_name,
            '" is already used in ',
            IF(v_report_dep > 0, CONCAT(v_report_dep, ' reports'), ''),
            IF(v_report_dep > 0 AND v_query_dep > 0, ' and ', ''),
            IF(v_query_dep > 0, CONCAT(v_query_dep, ' queries'), '')
        ) AS status;


        /* Result set 2 → query dependency list */
        IF v_query_dep > 0 THEN
            SELECT
                id,
                query_title,
                created_by,
                created_at
            FROM query_history
            WHERE session_id = p_session_id
              AND created_by = p_created_by
              AND table_names IS NOT NULL
              AND JSON_CONTAINS(table_names, JSON_QUOTE(v_table_name))
              AND is_execute = 1
            ORDER BY created_at DESC;
        END IF;


        /* Result set 3 → report dependency list */
        IF v_report_dep > 0 THEN
            SELECT
                sr.report_id,
                sr.report_name,
                sr.created_at
            FROM saved_reports sr
            JOIN query_history q ON q.id = sr.query_history_id
            WHERE sr.session_id = p_session_id
              AND sr.user_id = p_created_by
              AND q.table_names IS NOT NULL
              AND JSON_CONTAINS(q.table_names, JSON_QUOTE(v_table_name))
            ORDER BY sr.created_at DESC;
        END IF;


        LEAVE proc_block;
    END IF;


    /* --------------------------------
       Table MUST exist
    -------------------------------- */
    SELECT COUNT(*) INTO v_table_exists
    FROM information_schema.tables
    WHERE table_schema = DATABASE()
      AND table_name = v_table_name;


    IF v_table_exists = 0 THEN
        SELECT 'Table does not exist - delete operation aborted' AS status;
        LEAVE proc_block;
    END IF;


    /* --------------------------------
       Safe delete
    -------------------------------- */
    START TRANSACTION;


    SET @drop_sql = CONCAT('DROP TABLE `', v_table_name, '`');
    PREPARE stmt FROM @drop_sql;
    EXECUTE stmt;
    DEALLOCATE PREPARE stmt;


    DELETE FROM uploaded_files
    WHERE session_id = p_session_id
      AND created_by = p_created_by
      AND table_name = v_table_name;


    COMMIT;


    SELECT 'Table and all related metadata deleted successfully' AS status;


END
"""
    )


    # =====================================================
    # sp_get_dashboard_data
    # =====================================================
    c.execute("DROP PROCEDURE IF EXISTS sp_get_dashboard_data")
    c.execute(
        """
  CREATE PROCEDURE sp_get_dashboard_data(
        IN p_session_id VARCHAR(50),
        IN p_created_by VARCHAR(50)
    )
    BEGIN
              -- TOTAL FILE UPLOADS
        SELECT 
            COUNT(*) AS total_uploaded_files
        FROM uploaded_files
        WHERE created_by = p_created_by
        AND session_id = p_session_id
        AND table_extraction_status = 'done'
        AND column_extraction_status = 'done'
        OR data_insights_status = 'done';


        -- TOTAL FILE EXTRACTED
        SELECT 
            COUNT(*) AS table_extract_status
        FROM uploaded_files
        WHERE created_by = p_created_by
        AND session_id = p_session_id
        AND table_extraction_status = 'done';


        -- TOTAL REPORTS GENERATED
        SELECT 
            COUNT(*) AS total_reports_generated
        FROM saved_reports
        WHERE user_id = p_created_by
        AND session_id = p_session_id;


        -- TOTAL QUERIES GENERATED
        SELECT 
            COUNT(*) AS total_queries
        FROM query_history
        WHERE created_by = p_created_by 
        AND session_id = p_session_id;


        -- WORKING QUERIES (executed)
        SELECT 
            COUNT(*) AS working_queries
        FROM query_history
        WHERE created_by = p_created_by
        AND session_id = p_session_id
        AND is_execute = 1;


        -- MOST RECENTLY UPLOADED FILE DETAILS
        SELECT *
        FROM uploaded_files
        WHERE created_by = p_created_by
        AND session_id = p_session_id
        AND table_extraction_status = 'done'
        AND column_extraction_status = 'done'
        AND data_insights_status = 'done'
        -- ORDER BY updated_at DESC
        ORDER BY  COALESCE(updated_at, created_at) DESC
        LIMIT 1;
        -- AVG QUERY TIME
        SELECT
            ROUND(
                AVG(
                    CAST(
                        REPLACE(query_time, ' sec', '') AS DECIMAL(10,3)
                    )
                ), 3
            ) AS avg_query_time
        FROM query_history
        WHERE created_by = p_created_by
        AND session_id = p_session_id
        AND is_execute = 1
        AND query_time IS NOT NULL
        AND query_time != '';
        -- QUERY SUCCESS RATE
        SELECT
            ROUND(
                (SUM(is_success = 1) / COUNT(*)) * 100,
                2
            ) AS query_success_rate
        FROM query_history
        WHERE created_by = p_created_by
        AND session_id = p_session_id;
        -- AVG ROWS PER REPORT
        SELECT
            ROUND(AVG(row_affected), 0) AS avg_rows_per_report
        FROM saved_reports
        WHERE user_id = p_created_by
        AND session_id = p_session_id;
        -- FILE UPLOAD TREND
        SELECT
            DATE(created_at) AS upload_date,
            COUNT(*) AS total_files
        FROM uploaded_files
        WHERE created_by = p_created_by
        GROUP BY DATE(created_at)
        ORDER BY upload_date;
        -- QUERY ACTIVITY TREND
        SELECT
            DATE(created_at) AS query_date,
            COUNT(*) AS total_queries
        FROM query_history
        WHERE created_by = p_created_by
        GROUP BY DATE(created_at)
        ORDER BY query_date;


        -- TOP TABLES USED
        SELECT
            jt.table_name,
            COUNT(*) AS usage_count
        FROM query_history,
        JSON_TABLE(
            table_names,
            '$[*]' COLUMNS (
                table_name VARCHAR(100) PATH '$'
            )
        ) jt
        WHERE created_by = p_created_by
        GROUP BY jt.table_name
        ORDER BY usage_count DESC
        LIMIT 5;
    END
    """
    )
    # =====================================================
    # sp_get_full_table_info
    # =====================================================
    c.execute("DROP PROCEDURE IF EXISTS sp_get_full_table_info")
    c.execute(
        """
    CREATE PROCEDURE sp_get_full_table_info(
        IN p_created_by VARCHAR(100),
        IN p_session_id VARCHAR(100)
    )
    BEGIN
            SELECT DISTINCT
            table_name AS label,
            table_name AS value
        FROM uploaded_files
        WHERE created_by = p_created_by
        AND session_id = p_session_id
        AND table_extraction_status = 'done'
        AND column_extraction_status = 'done'
        AND data_insights_status = 'done'
        AND file_type != 'web_search';



        --  COLUMN METADATA FOR ALL TABLES (FIXED, LOGIC SAME)
        SELECT
            t.table_name,
            c.ORDINAL_POSITION AS column_id,
            c.COLUMN_NAME,
            c.DATA_TYPE
        FROM (
            SELECT DISTINCT table_name
            FROM uploaded_files
            WHERE created_by = p_created_by
            AND session_id = p_session_id
            AND table_extraction_status = 'done'
            AND column_extraction_status = 'done'
            AND data_insights_status = 'done'
            AND file_type != 'web_search'
        ) t
        JOIN INFORMATION_SCHEMA.COLUMNS c
        ON c.TABLE_NAME = t.table_name
        AND c.TABLE_SCHEMA = DATABASE()
        ORDER BY t.table_name, c.ORDINAL_POSITION;



        --  INSIGHTS FOR EACH TABLE (NO CHANGE)
        SELECT
            table_name,
            insights
        FROM uploaded_files
        WHERE created_by = p_created_by
        AND session_id = p_session_id
        AND table_extraction_status = 'done'
        AND column_extraction_status = 'done'
        AND data_insights_status = 'done'
        AND file_type != 'web_search';
    END
    """
    )


    # =====================================================
    # sp_get_query_details_by_user_session_id
    # =====================================================
    c.execute("DROP PROCEDURE IF EXISTS sp_get_query_details_by_user_session_id")
    c.execute(
        """
    CREATE PROCEDURE sp_get_query_details_by_user_session_id(
        IN p_created_by VARCHAR(100),
        IN p_session_id VARCHAR(100),
        IN p_workspace_id INT
    )
    BEGIN
         SELECT 
        q.id,
        q.query_title,
        q.user_query AS `query`,
        q.ai_response,


        q.is_execute,
        q.row_count AS rows_effected,
        q.query_time,


        q.mode,
        q.parent_query_id,
        q.version_no,
        q.is_latest,


        TIME_FORMAT(q.created_at, '%h:%i %p') AS created_at,
        DATE_FORMAT(q.created_at, '%d-%m-%Y') AS created_date,
        q.created_at AS actual_created_at,
         q.created_by,
        q.session_id,
        q.updated_by,
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
    """
    )
    #  COALESCE(q.parent_query_id, q.id),
    #   q.version_no DESC,
    # ============================================================
    # sp_get_report_list
    # ============================================================
    c.execute("DROP PROCEDURE IF EXISTS sp_get_report_list")
    c.execute(
        """
    CREATE PROCEDURE sp_get_report_list(
        IN p_session_id VARCHAR(100),
        IN p_user_id VARCHAR(100)
    )
    BEGIN
            SELECT
            r.report_id,
            r.report_name,
            r.query_history_id,          -- VERY IMPORTANT
            r.row_affected,
            r.report_config,
            r.created_at,
            TIME_FORMAT(r.created_at, '%h:%i %p') AS actual_created_at,
            DATE_FORMAT(r.created_at, '%d-%m-%Y') AS actual_created_date,
            r.updated_at,
            TIME_FORMAT(r.updated_at, '%h:%i %p') AS actual_saved_at,
            DATE_FORMAT(r.updated_at, '%d-%m-%Y') AS actual_saved_date,
            q.query_title,
            q.ai_response


        FROM saved_reports r
        INNER JOIN query_history q 
            ON q.id = r.query_history_id


        WHERE r.session_id = p_session_id
        AND r.user_id = p_user_id


        ORDER BY r.created_at DESC;
    END
    """
    )


    # ============================================================
    # sp_get_uploaded_files_status
    # ============================================================
    c.execute("DROP PROCEDURE IF EXISTS sp_get_uploaded_files_status")
    c.execute(
        """
    CREATE PROCEDURE sp_get_uploaded_files_status(
        IN p_created_by VARCHAR(100),
        IN p_session_id VARCHAR(100),
        IN p_workspace_id INT
    )
    BEGIN
        -- Normal Data
        SELECT 
            uf.id AS file_id,
            uf.file_name,
            uf.table_name,
            uf.file_size_mb,
            uf.file_type,
            -- uf.total_rows as rows_effected,
            uf.last_inserted_rows as rows_effected,
            uf.total_columns,


            COALESCE(uf.table_extraction_status, 'pending') AS table_extraction_status,
            COALESCE(uf.column_extraction_status, 'pending') AS column_extraction_status,
            COALESCE(uf.data_insights_status, 'pending') AS data_insights_status,
            COALESCE(uf.data_insert_status, 'pending') AS data_insert_status,


            uf.insights,
--  CONNECTED QUERY COUNT
        (
            SELECT COUNT(*)
            FROM query_history qh
            WHERE qh.session_id = uf.session_id
              AND qh.created_by = uf.created_by
              AND JSON_CONTAINS(qh.table_names, JSON_QUOTE(uf.table_name))
        ) AS connected_queries,


        --  CONNECTED REPORT COUNT
        (
            SELECT COUNT(*)
            FROM saved_reports sr
            JOIN query_history qh ON qh.id = sr.query_history_id
            WHERE qh.session_id = uf.session_id
              AND qh.created_by = uf.created_by
              AND JSON_CONTAINS(qh.table_names, JSON_QUOTE(uf.table_name))
        ) AS connected_reports,


        --  QUERY TITLES (JSON)
        (
            SELECT JSON_ARRAYAGG(qh.query_title)
            FROM query_history qh
            WHERE qh.session_id = uf.session_id
              AND qh.created_by = uf.created_by
              AND JSON_CONTAINS(qh.table_names, JSON_QUOTE(uf.table_name))
        ) AS query_titles,


        --  REPORT NAMES (JSON)
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
        -- ORDER BY uf.created_at DESC;
        ORDER BY  COALESCE(uf.updated_at, uf.created_at) DESC;



    END
    """
    )


    # ============================================================
    # sp_insert_uploaded_file
    # ============================================================
    c.execute("DROP PROCEDURE IF EXISTS sp_insert_uploaded_file")
    c.execute(
        """
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
        proc_main: BEGIN


            DECLARE v_pending_id INT DEFAULT NULL;


            /* ------------------------------------------------
            STEP 1: Find pending row (table created, no data yet)
            ------------------------------------------------ */
            SELECT id
            INTO v_pending_id
            FROM uploaded_files
            WHERE session_id = p_session_id
            AND table_name = p_table_name
            AND data_insert_status = 'pending'
            ORDER BY created_at ASC
            LIMIT 1;


            /* ------------------------------------------------
            STEP 2: FIRST DATA INSERT → UPDATE pending row
            ------------------------------------------------ */
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
                    updated_at = NOW()
                WHERE id = v_pending_id;


                SELECT v_pending_id AS file_id, 'UPDATED' AS status_flag;
                LEAVE proc_main;
            END IF;


            /* ------------------------------------------------
            STEP 3: INSERT NEW ROW
            - Table create
            - OR re-insert history
            ------------------------------------------------ */
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
                last_inserted_rows,
                created_by,
                created_at,
                table_extraction_status,
                column_extraction_status,
                insights,
                data_insights_status,
                data_insert_status
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
                p_last_inserted_rows,
                p_created_by,
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
    )


    # ============================================================
    # sp_save_or_update_report
    # ============================================================
    c.execute("DROP PROCEDURE IF EXISTS sp_save_or_update_report")
    c.execute(
        """
    CREATE PROCEDURE sp_save_or_update_report(
           IN p_report_id VARCHAR(100),
        IN p_session_id VARCHAR(100),
        IN p_user_id VARCHAR(100),
        IN p_report_name VARCHAR(255),
        IN p_query_history_id INT,
        IN p_row_affected INT,
        IN p_report_config JSON, 
        OUT p_action VARCHAR(20)   -- INSERT / UPDATE / EXISTS
    )
    BEGIN
        DECLARE v_existing_query INT;
        DECLARE v_existing_name VARCHAR(255); -- new


        
        SELECT query_history_id, report_name
        INTO v_existing_query, v_existing_name


        FROM saved_reports
        WHERE report_id = p_report_id
        AND session_id = p_session_id
        AND user_id = p_user_id
        LIMIT 1;


        -- CASE 1: No report → INSERT
        IF v_existing_query IS NULL THEN


            INSERT INTO saved_reports
            (report_id, session_id, user_id, report_name, query_history_id, row_affected,report_config)
            VALUES
            (p_report_id, p_session_id, p_user_id, p_report_name, p_query_history_id, p_row_affected, p_report_config);


            SET p_action = 'INSERT';


    
      -- CASE 3: Different query → UPDATE
        ELSE
            UPDATE saved_reports
            SET
                report_name = p_report_name,
                query_history_id = p_query_history_id,
                row_affected = p_row_affected,
                 report_config = p_report_config, 
                updated_at = NOW()
            WHERE report_id = p_report_id
            AND session_id = p_session_id
            AND user_id = p_user_id;


            SET p_action = 'UPDATE';
        END IF;


    END
    """
    )
    #   -- CASE 2: Same query → EXISTS


    #        ELSEIF v_existing_query = p_query_history_id
    #        AND v_existing_name = p_report_name THEN
    #        SET p_action = 'EXISTS';
    # ============================================================
    # sp_save_query
    # ============================================================
    c.execute("DROP PROCEDURE IF EXISTS sp_save_query")
    c.execute(
        """
    CREATE PROCEDURE sp_save_query(
        IN p_session_id VARCHAR(100),
        IN p_workspace_id INT,
        IN p_created_by VARCHAR(100),
        IN p_query_title VARCHAR(150),


        IN p_message_query_id BIGINT,
        IN p_user_query TEXT,
        IN p_ai_response LONGTEXT,
        IN p_executable_sql LONGTEXT,
        IN p_table_names JSON,


        IN p_is_execute TINYINT,
        IN p_is_success TINYINT,
        IN p_row_count INT,
        IN p_query_time VARCHAR(50),


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
            version_no,
            parent_query_id,
            is_latest,
            created_at
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
            'NEW',
            1,
            p_parent_query_id,
            1,
            NOW()
        );


        SELECT LAST_INSERT_ID() AS saved_id;
    END
    """
    )


    # ============================================================
    # sp_refresh_query_row_counts
    # ============================================================
    c.execute("DROP PROCEDURE IF EXISTS sp_refresh_query_row_counts")
    c.execute(
        """
        CREATE PROCEDURE sp_refresh_query_row_counts()
        BEGIN
            DECLARE done INT DEFAULT 0;
            DECLARE v_query_id INT;
            DECLARE v_sql LONGTEXT;
            DECLARE v_row_count INT;


            DECLARE cur CURSOR FOR
                SELECT id, executable_sql
                FROM query_history
                WHERE executable_sql IS NOT NULL
                AND is_execute = 1
                AND is_latest = 1;


            DECLARE CONTINUE HANDLER FOR NOT FOUND SET done = 1;


            -- TEMP TABLE must be created AFTER DECLAREs
            DROP TEMPORARY TABLE IF EXISTS tmp_cnt;
            CREATE TEMPORARY TABLE tmp_cnt (cnt INT);


            OPEN cur;


            read_loop: LOOP
                FETCH cur INTO v_query_id, v_sql;
                IF done = 1 THEN
                    LEAVE read_loop;
                END IF;


                DELETE FROM tmp_cnt;


                SET @dyn_sql = CONCAT(
                    'INSERT INTO tmp_cnt ',
                    'SELECT COUNT(*) FROM (', v_sql, ') t'
                );


                PREPARE stmt FROM @dyn_sql;
                EXECUTE stmt;
                DEALLOCATE PREPARE stmt;


                SELECT cnt INTO v_row_count FROM tmp_cnt LIMIT 1;


                UPDATE query_history
                SET row_count = v_row_count,
                    updated_at = NOW()
                WHERE id = v_query_id;


                UPDATE saved_reports
                SET row_affected = v_row_count,
                    updated_at = NOW()
                WHERE query_history_id = v_query_id;
            END LOOP;


            CLOSE cur;
            DROP TEMPORARY TABLE IF EXISTS tmp_cnt;
        END
    """
    )
    c.close()



def admin_company_register_controller():
    try:
        # JSON Payload theke data neowa hocche
        if not request.is_json:
            return build_response(False, "Content-Type must be application/json", 415)
            
        data = request.get_json()
        if not data:
            return build_response(False, "No JSON data provided", 400)


        # Apnar Payload onujayi data map kora (Baki gulo NULL thakbe)
        company_name = data.get("company_name")
        company_email = data.get("company_email")
        gst_number = data.get("gst_number")
        phone_number = data.get("phone_number")
        dial_code=data.get("dial_code")
        address = data.get("address")
        city = data.get("city")
        country = data.get("country")
        pin_code = data.get("pin_code")
        from_date = data.get("from_date")
        to_date = data.get("to_date")
        subscription_amount = data.get("subscription_amount")
        
        # Optional field (jodi dorkar hoy, na thakle default null)
        company_id = data.get("id")
        created_by = data.get("created_by")


        # Mandatory Field Validation
        if not company_name or not company_email:
            return build_response(False, "Company name and email are required", 400)


        # Validate date gap (At least 1 year)
        if from_date and to_date:
            try:
                fd = datetime.strptime(from_date, "%Y-%m-%d")
                td = datetime.strptime(to_date, "%Y-%m-%d")
                
                try:
                    one_year_later = fd.replace(year=fd.year + 1)
                except ValueError:
                    # Leap year case: Feb 29 + 1 year -> Feb 28 of non-leap year
                    one_year_later = fd.replace(year=fd.year + 1, day=28)
                    
                if td < one_year_later:
                    return build_response(False, "To date must be at least 1 year after From date", 400)
            except ValueError as val_err:
                return build_response(False, f"Invalid date format: {str(val_err)}", 400)


        master = get_master_db()
        master_cursor = master.cursor(dictionary=True)


        # Uniqueness checks (excluding soft-deleted companies, and current company if editing)
        clean_name = company_name.strip() if (company_name and isinstance(company_name, str)) else ''
        clean_email = company_email.strip() if (company_email and isinstance(company_email, str)) else ''
        clean_gst = gst_number.strip() if (gst_number and isinstance(gst_number, str)) else ''


        check_query = """
            SELECT company_name, company_email, gst_number
            FROM companies
            WHERE is_deleted = 0
              AND (
                  company_name = %s 
                  OR company_email = %s 
                  OR (%s != '' AND gst_number IS NOT NULL AND gst_number != '' AND gst_number = %s)
              )
        """
        check_params = [clean_name, clean_email, clean_gst, clean_gst]
        
        if company_id:
            check_query += " AND id != %s"
            check_params.append(company_id)
            
        master_cursor.execute(check_query, tuple(check_params))
        duplicates = master_cursor.fetchall()
        
        if duplicates:
            for dup in duplicates:
                dup_name = dup["company_name"].strip().lower() if dup["company_name"] else ""
                dup_email = dup["company_email"].strip().lower() if dup["company_email"] else ""
                dup_gst = dup["gst_number"].strip().lower() if dup["gst_number"] else ""
                
                if dup_name == clean_name.lower():
                    master_cursor.close()
                    master.close()
                    return build_response(False, "Company name already exists", 409)
                if dup_email == clean_email.lower():
                    master_cursor.close()
                    master.close()
                    return build_response(False, "Company email already exists", 409)
                if clean_gst and dup_gst == clean_gst.lower():
                    master_cursor.close()
                    master.close()
                    return build_response(False, "GST number already exists", 409)
            
            master_cursor.close()
            master.close()
            return build_response(False, "Company name, email, or GST number already exists", 409)


        # ==================================================
        # UPDATE LOGIC
        # ==================================================
        if company_id:
            master_cursor.execute("""
                UPDATE companies
                SET
                    company_name=%s, gst_number=%s, company_email=%s, phone_number=%s,dial_code=%s,
                    address=%s, city=%s, country=%s, pin_code=%s,
                    subscription_amount=%s, from_date=%s, to_date=%s, updated_at=NOW()
                WHERE id=%s AND is_deleted=0
            """, (
                company_name, gst_number, company_email, phone_number,dial_code,
                address, city, country, pin_code,
                subscription_amount, from_date, to_date, company_id
            ))
            master.commit()
            master.close()
            return build_response(True, "Company updated successfully", 200)


        # ==================================================
        # INSERT LOGIC
        # ==================================================
        company_code = generate_company_code(company_name, master_cursor)
        company_db_name = f"sahaj_cmp_{company_code}"


        try:
            master_cursor.execute("""
                INSERT INTO companies (
                    company_name, gst_number, company_code, company_email,
                    phone_number, dial_code ,address, city, country, pin_code,
                    subscription_amount, from_date, to_date,
                    company_db_name, created_by, is_active, is_deleted, created_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 1, 0, NOW())
            """, (
                company_name, gst_number, company_code, company_email,
                phone_number,dial_code, address, city, country, pin_code,
                subscription_amount, from_date, to_date,
                company_db_name, created_by
            ))
            master.commit()
            company_id = master_cursor.lastrowid
        except mysql.connector.IntegrityError:
            master.rollback()
            return build_response(False, "Company or Email already exists", 409)


        # Company Database creation
        master_cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{company_db_name}`")
        master.commit()
        master_cursor.close()
        master.close()


        # ==================================================
        # CREATE COMPANY TABLES (Inside New DB)
        # ==================================================
        company_conn = mysql.connector.connect(
            host=MASTER_DB_HOST,
            user=MASTER_DB_USER,
            password=MASTER_DB_PASS,
            database=company_db_name,
        )
        c = company_conn.cursor()


        # ---------------- USER ROLES ----------------
        c.execute(
            f"""
CREATE TABLE IF NOT EXISTS user_roles (
    id INT AUTO_INCREMENT PRIMARY KEY,
    role_name VARCHAR(50) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)ENGINE={DB_ENGINE} DEFAULT CHARSET={DB_CHARSET}
"""
        )


        # Default roles
        c.execute(
            """
        INSERT IGNORE INTO user_roles (id, role_name)
        VALUES
        (1, 'companyadmin'),
        (2, 'user')
"""
        )


        # Insert default Admin role
        # ---------------- USERS (COMPANY DB) ----------------
        c.execute(
            f"""
        CREATE TABLE IF NOT EXISTS users (
    id INT AUTO_INCREMENT PRIMARY KEY,


    user_id VARCHAR(50) UNIQUE,
    full_name VARCHAR(100),
    email VARCHAR(100),
    phone_number VARCHAR(20),
    address VARCHAR(255),
    password_hash VARCHAR(255) NOT NULL,
    plain_password VARCHAR(100),
    app_role_id INT NOT NULL,
    company_id INT NOT NULL,


    session_id VARCHAR(36),


    created_by VARCHAR(50),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,


    updated_by VARCHAR(50),
    updated_at DATETIME DEFAULT NULL,
    is_active TINYINT DEFAULT 1,
    is_deleted TINYINT DEFAULT 0,
    deleted_by VARCHAR(50),
    deleted_at TIMESTAMP NULL
   
)ENGINE={DB_ENGINE} DEFAULT CHARSET={DB_CHARSET}
"""
        )


        # ---------------- WORKSPACES (COMPANY DB) ----------------
        c.execute(
            f"""
        CREATE TABLE IF NOT EXISTS workspaces (
            id INT AUTO_INCREMENT PRIMARY KEY,
            workspace_name VARCHAR(255) NOT NULL,
            created_by VARCHAR(100),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )ENGINE={DB_ENGINE} DEFAULT CHARSET={DB_CHARSET}
        """
        )


        # ---------------- WORKSPACE_USERS (COMPANY DB) ----------------
        c.execute(
            f"""
        CREATE TABLE IF NOT EXISTS workspace_users (
            id INT AUTO_INCREMENT PRIMARY KEY,
            workspace_id INT NOT NULL,
            user_email VARCHAR(100) NOT NULL,
            assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE
        )ENGINE={DB_ENGINE} DEFAULT CHARSET={DB_CHARSET}
        """
        )


        # ---------------- UPLOADED FILES ----------------
        c.execute(
            f"""
        CREATE TABLE IF NOT EXISTS uploaded_files (
        id INT AUTO_INCREMENT PRIMARY KEY,
        session_id VARCHAR(100),
        workspace_id INT,
        file_name VARCHAR(255),
        table_name VARCHAR(255),
        file_size_mb varchar(100),
        file_type VARCHAR(20),


        actual_rows INT,
        actual_columns INT,
        total_rows INT,
        total_columns INT,
        last_inserted_rows INT DEFAULT 0,


        created_by VARCHAR(100),
        updated_by VARCHAR(100),


        insights LONGTEXT,


        table_extraction_status VARCHAR(20),
        column_extraction_status VARCHAR(20),
        data_insights_status VARCHAR(20),
        data_insert_status VARCHAR(20),


        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP NULL
    )ENGINE={DB_ENGINE} DEFAULT CHARSET={DB_CHARSET}
    """
        )


        # ---------------- QUERY HISTORY ----------------
        c.execute(
            f"""
    CREATE TABLE IF NOT EXISTS query_history (
           id INT AUTO_INCREMENT PRIMARY KEY,


            session_id VARCHAR(100) NOT NULL,
            workspace_id INT,
            created_by VARCHAR(100) NOT NULL,


            query_title VARCHAR(150),
            message_query_id BIGINT,          


            user_query TEXT,
            ai_response LONGTEXT,
            executable_sql LONGTEXT,
            table_names JSON,


            is_execute TINYINT DEFAULT 0,
            is_success TINYINT DEFAULT 0,
            row_count INT DEFAULT 0,
            query_time VARCHAR(50),


            mode VARCHAR(20),                 
            version_no INT DEFAULT 1,
            parent_query_id INT NULL,
            is_latest TINYINT DEFAULT 1,


            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP NULL,
            updated_by VARCHAR(100) NULL
        )ENGINE={DB_ENGINE} DEFAULT CHARSET={DB_CHARSET}
        """
        )


        # ---------------- SAVED REPORTS ----------------
        c.execute(
            f"""
    CREATE TABLE IF NOT EXISTS saved_reports (
        id INT AUTO_INCREMENT PRIMARY KEY,
        report_id VARCHAR(100),
        report_name VARCHAR(255),
        query_history_id INT,
        row_affected INT,
        report_config JSON,
        user_id VARCHAR(100),
        session_id VARCHAR(100),


        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP NULL
    )ENGINE={DB_ENGINE} DEFAULT CHARSET={DB_CHARSET}
    """
        )


        # ---------------- upload progress----------------
        c.execute(
            f"""     
        CREATE TABLE upload_progress (
        id INT AUTO_INCREMENT PRIMARY KEY,
        session_id VARCHAR(100),
        file_name VARCHAR(255),
        file_hash CHAR(32),
        processed_rows BIGINT DEFAULT 0,
        total_rows BIGINT DEFAULT 0,
        status VARCHAR(20),
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE KEY uq_progress_hash (file_hash)
    )ENGINE={DB_ENGINE} DEFAULT CHARSET={DB_CHARSET}
    """
        )
        company_conn.commit()


        # ---------------- normalized knowledge ----------------
        c.execute(
            f"""
        CREATE TABLE IF NOT EXISTS normalized_knowledge (
            id INT AUTO_INCREMENT PRIMARY KEY,
            company_code VARCHAR(50),
            session_id VARCHAR(100),
            workspace_id INT,
            source_type VARCHAR(50),
            source_name VARCHAR(255),
            content LONGTEXT,
            metadata JSON,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        ) ENGINE={DB_ENGINE} DEFAULT CHARSET={DB_CHARSET}
        """
        )
        company_conn.commit()
        c.close()
        company_conn.close()


        # Stored Procedures
        create_stored_procedures(company_db_name)
        return build_response(True, "Company registered successfully", 200, extra={"company_db": company_db_name})


    except Exception as e:
        return build_response(False, "Server error", 500, data={"error": str(e)})


# controller file-e get_country_options function-ti thik korun
def get_country_options():
    try:
        master = get_master_db()
        # buffered=True use kora hoyeche jate result set clean thake
        cursor = master.cursor(dictionary=True, buffered=True)


        # Sob country select kora hochche
        query = "SELECT country_name, country_code, dial_code FROM countries ORDER BY country_name ASC"
        cursor.execute(query)
        rows = cursor.fetchall()


        cursor.close()
        master.close()


        # Data-ke object list hisabe format kora
        country_list = [
            {
                "label": row["country_name"],
                "value": row["country_code"],
                "dialCode": row["dial_code"]
            }
            for row in rows
        ]


        if country_list:
            return build_response(True, "Country list fetched successfully", 200, data=country_list)
        else:
            return build_response(False, "No countries found in database", 404)


    except Exception as e:
        return build_response(False, "Server error", 500, data={"error": str(e)})