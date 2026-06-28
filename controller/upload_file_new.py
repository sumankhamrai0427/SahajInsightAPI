# app_csv_pipeline.py
"""
Clean, single-endpoint CSV pipeline for Flask (Option A - clean & readable)
Supports actions: upload, preview, insert_data
Features:
- Robust CSV loading with encoding and delimiter sniffing
- Header cleaning (never return null/empty header names)
- LLM schema inference with strict primary-key rules + fail-safes
- Preview (deduped + cleaned)
- Insert with CREATE TABLE (if new) + upsert + metadata SP call
- JSON-safe responses via build_response
"""

import os
import re
import json
import csv
import hashlib
import pandas as pd
import numpy as np
from flask import request,g
from werkzeug.utils import secure_filename

# Project helpers (must exist)
from helper.helperFunctions import (
    build_response,
    format_file_size,
    allowed_file,
    get_upload_folder,
    make_file_hash
)
from model.llm_client import call_llm

UPLOAD_FOLDER = get_upload_folder()
os.makedirs(UPLOAD_FOLDER, exist_ok=True)


def remove_row_hash(rows):
    """
    Remove row_hash key from list of dict rows
    """
    clean = []
    for r in rows:
        if isinstance(r, dict):
            r = dict(r)          # safe copy
            r.pop("row_hash", None)
        clean.append(r)
    return clean


# def normalize_date_columns(df: pd.DataFrame, schema: list):
#     """
#     Convert CSV date values to MySQL DATE format (YYYY-MM-DD)
#     """
#     date_cols = [
#         c["column"]
#         for c in schema
#         if str(c.get("datatype", "")).upper() == "DATE"
#     ]

#     for col in date_cols:
#         if col not in df.columns:
#             continue

#         df[col] = pd.to_datetime(
#             df[col],
#             errors="coerce",          # invalid → NaT
#             infer_datetime_format=True
#         ).dt.strftime("%Y-%m-%d")

#         # NaT → None (important for MySQL)
#         df[col] = df[col].where(pd.notnull(df[col]), None)

#     return df

def normalize_date_columns(df: pd.DataFrame, schema: list):
    """
    Convert CSV date/datetime values to MySQL-safe formats
    DATE      → YYYY-MM-DD
    DATETIME  → YYYY-MM-DD HH:MM:SS
    """
    for col_def in schema:
        col = col_def.get("column")
        dtype = str(col_def.get("datatype", "")).upper()

        if col not in df.columns:
            continue

        # DATE
        if dtype == "DATE":
            df[col] = pd.to_datetime(
                df[col],
                errors="coerce"
            ).dt.strftime("%Y-%m-%d")

        # DATETIME
        elif dtype == "DATETIME":
            df[col] = pd.to_datetime(
                df[col],
                errors="coerce"
            ).dt.strftime("%Y-%m-%d %H:%M:%S")

        # NaT → None (important)
        df[col] = df[col].where(pd.notnull(df[col]), None)

    return df

def align_csv_to_schema(df: pd.DataFrame, schema: list, drop_unmapped=False):
    """
    Map and rename the columns of df (CSV) to match the target database schema.
    Returns a new DataFrame where columns match the schema.
    If a schema column is not found/mapped to CSV, it will be initialized as None
    (or populated with UUIDs for string primary keys, or dropped if drop_unmapped is True).
    """
    import uuid
    df = df.copy()
    
    # Clean the CSV column names just like we did in upload
    df.columns = clean_column_names(df.columns)
    
    csv_cols = list(df.columns)
    schema_cols = [c["column"] for c in schema]
    
    mapping = {} # maps schema_col -> csv_col
    used_csv_cols = set()
    
    # Helper to normalize a string (lowercase, alphanumeric only)
    def norm(s):
        return re.sub(r'[^a-z0-9]', '', str(s).lower())

    # Pass 1: Try exact match (case-insensitive and normalized)
    for scol in schema_cols:
        scol_norm = norm(scol)
        for ccol in csv_cols:
            if ccol in used_csv_cols:
                continue
            if norm(ccol) == scol_norm:
                mapping[scol] = ccol
                used_csv_cols.add(ccol)
                break

    # Pass 1.5: Match by stripping common suffixes/prefixes (e.g. salesperson_id -> salesperson)
    unmapped_schema_cols = [c for c in schema_cols if c not in mapping]
    
    def strip_helper(s):
        s = str(s).lower().strip()
        # strip common endings
        for suffix in ['_id', 'id', '_no', 'no', '_code', 'code', '_num', 'num', '_name', 'name']:
            if s.endswith(suffix) and len(s) > len(suffix):
                s = s[:-len(suffix)]
        # strip common starts
        for prefix in ['id_', 'num_', 'no_']:
            if s.startswith(prefix) and len(s) > len(prefix):
                s = s[len(prefix):]
        return re.sub(r'[^a-z0-9]', '', s)

    for scol in unmapped_schema_cols:
        scol_stripped = strip_helper(scol)
        if not scol_stripped:
            continue
        for ccol in csv_cols:
            if ccol in used_csv_cols:
                continue
            if strip_helper(ccol) == scol_stripped:
                mapping[scol] = ccol
                used_csv_cols.add(ccol)
                break

    # Pass 2: Fuzzy/Sub-string match or positional fallback for remaining columns
    unmapped_schema_cols = [c for c in schema_cols if c not in mapping]
    unmapped_csv_cols = [c for c in csv_cols if c not in used_csv_cols]
    
    schema_info = {c["column"]: c for c in schema}
    
    # Identify which schema columns are "generated PKs"
    generated_pks = set()
    for scol in unmapped_schema_cols:
        col_def = schema_info[scol]
        if col_def.get("primary"):
            # Check if there is any column in the CSV that looks like a primary key
            has_csv_pk = any(norm(cc) in ("id", "uuid", norm(scol)) for cc in csv_cols)
            if not has_csv_pk:
                generated_pks.add(scol)
                
    # Map the remaining non-generated columns positionally
    remaining_schema_cols = [c for c in unmapped_schema_cols if c not in generated_pks]
    
    for i, scol in enumerate(remaining_schema_cols):
        if i < len(unmapped_csv_cols):
            mapping[scol] = unmapped_csv_cols[i]
            used_csv_cols.add(unmapped_csv_cols[i])
            
    # Now reconstruct the dataframe using the schema columns
    new_df = pd.DataFrame(index=df.index)
    for scol in schema_cols:
        if scol in mapping:
            new_df[scol] = df[mapping[scol]]
        else:
            # Check if this column is a primary key in schema
            col_def = schema_info.get(scol, {})
            if col_def.get("primary"):
                dtype = str(col_def.get("datatype", "")).upper()
                # If it's not an integer type, it's not auto-incremented by MySQL
                if dtype not in ("INT", "INTEGER", "BIGINT"):
                    # Generate UUIDs for all rows
                    new_df[scol] = [str(uuid.uuid4()) for _ in range(len(df))]
                    continue
            
            if not drop_unmapped:
                new_df[scol] = None
            
    return new_df

def build_preview_response(file_name, table_name, schema=None, is_existing=False, has_header=True):
    path = os.path.join(UPLOAD_FOLDER, file_name)
    if not os.path.exists(path):
        raise Exception("CSV file missing")

    df = load_csv(path, has_header)
    df.columns = clean_column_names(df.columns)
    df = df.where(pd.notnull(df), None)

    # ---------- NEW TABLE ----------
    if not is_existing:
        if not schema:
            raise Exception("Schema required for new table preview")
        df = align_csv_to_schema(df, schema)

    # ---------- COMMON ----------
    df = normalize_boolean_columns(df)
    df_clean = df.drop_duplicates().dropna(how="all")

    return {
        "table_name": table_name,
        "total_rows": df_clean.shape[0],
        "preview_rows": df_clean.head(5).fillna("").to_dict(orient="records")
    }


# -------------------------
# Utilities
# -------------------------

# =========================
# CSV Header Handling
# =========================

def load_csv(path, has_header: bool, chunksize=None):
    """
    Load CSV based on header flag with robust handling of bad lines and custom delimiters.
    """
    kwargs = {
        "dtype": str,
        "encoding": "utf-8-sig",
    }
    if not has_header:
        kwargs["header"] = None
    if chunksize is not None:
        kwargs["chunksize"] = chunksize

    # First attempt: standard comma-separated load
    try:
        return pd.read_csv(path, **kwargs)
    except Exception:
        # Second attempt: sniff delimiter and skip bad lines
        delimiter = ','
        try:
            with open(path, "r", encoding="utf-8-sig", errors="ignore") as fh:
                sample = fh.read(4096)
                try:
                    dialect = csv.Sniffer().sniff(sample)
                    delimiter = dialect.delimiter
                except Exception:
                    delimiter = ','
        except Exception:
            pass

        kwargs["delimiter"] = delimiter

        try:
            return pd.read_csv(path, on_bad_lines='skip', **kwargs)
        except TypeError:
            try:
                return pd.read_csv(path, error_bad_lines=False, **kwargs)
            except Exception:
                # If everything fails, try reading without bad lines flag just in case
                return pd.read_csv(path, **kwargs)


def apply_default_headers(df: pd.DataFrame):
    """
    Assign default column names when file has no header
    """
    df.columns = [f"column{i+1}" for i in range(df.shape[1])]
    return df


def validate_header_vs_table(has_header: bool, is_existing: bool):
    """
    Business rule validation
    """
    if not has_header and is_existing:
        raise ValueError(
            "File without header cannot be used with existing table"
        )



def to_python(v):
    if isinstance(v, (np.integer, np.int64, np.int32)):
        return int(v)
    if isinstance(v, (np.floating, np.float64, np.float32)):
        return float(v)
    if isinstance(v, (np.bool_, bool)):
        return bool(v)
    if v is None:
        return None
    return str(v)


def sanitize_table_name(fname):
    base = os.path.splitext(fname)[0]
    return re.sub(r"[^a-z0-9_]", "_", base.lower())


def clean_column_names(columns):
    """
    Ensure no null/empty headers. Normalize to word chars and ensure uniqueness.
    """
    s = list(columns)
    clean = []
    seen = {}
    for i, c in enumerate(s):
        name = c
        if name is None:
            name = ""
        name = str(name).strip()
        if name == "" or name.lower() in ["nan", "none"]:
            name = f"col_{i}"
        else:
            name = re.sub(r"[^\w]", "_", name)
            if name == "":
                name = f"col_{i}"
        # uniqueness
        if name in seen:
            seen[name] += 1
            name = f"{name}_{seen[name]}"
        else:
            seen[name] = 0
        clean.append(name)
    return clean


def _make_row_hash(values):
    s = "|".join("" if v is None else str(v) for v in values)
    return hashlib.md5(s.encode()).hexdigest()


def safe_parse_json(text):
    """
    Try robust parsing for LLM outputs.
    """
    if not isinstance(text, str):
        raise ValueError("safe_parse_json expects a string")
    s = text.strip()
    s = re.sub(r"```(?:json)?", "", s, flags=re.IGNORECASE).strip()
    # find first { or [
    starts = [idx for idx in (s.find("["), s.find("{")) if idx != -1]
    if starts:
        s = s[min(starts):]
    # try several fixes
    attempts = [s, s.replace("True", "true").replace("False", "false")]
    tmp = attempts[-1]
    tmp2 = re.sub(r"(?<![A-Za-z0-9_])'([^']*?)'(?![A-Za-z0-9_])", r'"\1"', tmp)
    attempts.append(tmp2)
    attempts.append(re.sub(r",\s*(\}|\])", r"\1", tmp2))
    last_err = None
    for a in attempts:
        try:
            return json.loads(a)
        except Exception as e:
            last_err = e
    raise ValueError(f"safe_parse_json failed: {last_err}")


def infer_schema_with_llm(df: pd.DataFrame, file_name: str):
    try:
        # -----------------------------------
        # CLEAN HEADERS
        # -----------------------------------
        cleaned_cols = clean_column_names(df.columns)
        df = df.copy()
        df.columns = cleaned_cols

        sample = df.head(500).fillna("").to_dict(orient="records")

        stats = {}

        # -----------------------------------
        # COLUMN TYPE DETECTION
        # -----------------------------------
        DATE_REGEX = (
            r"^\d{4}-\d{2}-\d{2}$|"      # yyyy-mm-dd
            r"^\d{2}/\d{2}/\d{4}$|"      # dd/mm/yyyy
            r"^\d{2}-\d{2}-\d{4}$|"      # dd-mm-yyyy
            r"^\d{4}/\d{2}/\d{2}$"       # yyyy/mm/dd
        )

        for col in df.columns:
            ser = df[col].dropna().astype(str)

            max_len = int(ser.str.len().max()) if not ser.empty else 0
            distinct = int(ser.nunique()) if not ser.empty else 0

            integer = bool(not ser.empty and ser.str.match(r"^-?\d+$").all())
            decimal = bool(not ser.empty and ser.str.match(r"^-?\d+\.\d+$").all())

            boolean_like = bool(
                not ser.empty and ser.str.lower().isin(
                    ["true", "false", "yes", "no", "0", "1"]
                ).all()
            )

            json_like = bool(
                not ser.empty and ser.str.strip().str.startswith(("{", "[")).all()
            )

            # ---------- FIXED DATE DETECTION ----------
            date_like = bool(
                not ser.empty
                and ser.head(10).str.match(DATE_REGEX).all()
            )

            unique = bool(not ser.empty and ser.nunique() == len(ser))

            stats[col] = {
                "max_len": max_len,
                "distinct": distinct,
                "integer": integer,
                "decimal": decimal,
                "boolean_like": boolean_like,
                "json_like": json_like,
                "date_like": date_like,
                "unique": unique
            }

        # -----------------------------------
        # LLM PROMPT
        # -----------------------------------

            prompt = f"""
You are a Senior MySQL Data Architect.

Your task:
Generate a SAFE, PRODUCTION-READY MySQL table schema.

STRICT RULES (MUST FOLLOW):
1. Always return VALID MySQL datatypes only.
2. If datatype is VARCHAR or CHAR:
   - Length is MANDATORY
   - Length MUST be <= 255
   - If unsure, use VARCHAR(255)
3. Never assign length to:
   - TEXT, MEDIUMTEXT, LONGTEXT
   - INT, BIGINT, FLOAT, DOUBLE
   - DATE, DATETIME, TIME, YEAR
4. For DECIMAL:
   - Always use DECIMAL(18,2) unless strong evidence suggests otherwise
5. BOOLEAN values must be TINYINT(1)
6. JSON-like values must use JSON datatype
7. Only ONE column can be PRIMARY KEY
8. Primary key preference order:
   uuid > id > *_id > code > number
9. Never invent columns
10. Never return NULL or empty column names
11. Analyze up to FIRST 500 ROWS for better accuracy

OUTPUT FORMAT (IMPORTANT):
Return ONLY a JSON ARRAY.
Each object MUST have:
- column
- datatype
- length (ONLY if datatype supports length)
- primary (true/false)

DO NOT include explanations or markdown.

Column statistics:
{json.dumps(stats, indent=2)}

Sample data (first 500 rows):
{json.dumps(sample, indent=2)}
"""
        raw = call_llm(prompt).strip().replace("```", "")
        parsed = safe_parse_json(raw)

        if not isinstance(parsed, list):
            raise ValueError("LLM did not return JSON array")

        # -----------------------------------
        # FORMAT FINAL SCHEMA
        # -----------------------------------
        final = []

        for idx, item in enumerate(parsed):
            if not isinstance(item, dict):
                continue

            name = item.get("column") or item.get("name") or item.get("col")

            if not name:
                name = cleaned_cols[idx] if idx < len(cleaned_cols) else f"col_{idx}"

            typ = (item.get("type") or item.get("datatype") or "VARCHAR").upper()
            length = item.get("length")

            if isinstance(length, str) and length.isdigit():
                length = int(length)
            elif isinstance(length, (np.integer, int)):
                length = int(length)
            else:
                length = None

            primary = bool(item.get("primary", False))

            final.append({
                "column": name,
                "datatype": typ,
                "length": length,
                "primary": primary
            })

        # -----------------------------------------------
        # ** PRIMARY KEY RULE: ONLY ONE PK ALLOWED **
        # -----------------------------------------------
        pk_candidates = [c for c in final if c.get("primary")]

        if len(pk_candidates) > 1:

            def pk_priority(col):
                name = col["column"].lower()
                if "uuid" in name: return 1
                if name == "id" or name.endswith("_id"): return 2
                if "code" in name: return 3
                if "number" in name or name.endswith("no"): return 4
                return 5

            best = sorted(pk_candidates, key=pk_priority)[0]

            for col in final:
                col["primary"] = (col["column"] == best["column"])

        # AUTOMATIC ID GENERATION RULE:
        # If 'id' column is not found in the final schema, automatically create an 'id' column 
        # and treat it as the primary key.
        id_exists = any(c["column"].lower() == "id" for c in final)
        if not id_exists:
            final.insert(0, {
                "column": "id",
                "datatype": "INT",
                "length": None,
                "primary": True
            })
            # Ensure only this injected 'id' is marked as primary
            for col in final[1:]:
                col["primary"] = False
        else:
            # If 'id' exists, make sure at least one column is marked primary.
            # If no column is primary, mark the 'id' column as primary.
            pk_exists = any(c.get("primary") for c in final)
            if not pk_exists:
                for col in final:
                    if col["column"].lower() == "id":
                        col["primary"] = True
                        break

        return final

    except Exception as ex:
        return [{"error": "LLM Schema Error", "message": str(ex)}]

# -------------------------
# Schema compare helpers
# -------------------------
def normalize_type_for_compare(typ):
    if not typ:
        return "string"
    t = str(typ).lower()
    if t.startswith("varchar") or t.startswith("char") or t in ("text", "mediumtext", "longtext"):
        return "string"
    if t in ("int", "integer", "bigint", "smallint", "tinyint"):
        return "int"
    if t in ("float", "double", "decimal"):
        return "float"
    if t in ("date", "datetime", "time", "year"):
        return "date"
    if "json" in t:
        return "json"
    return "string"


def compare_schemas(file_schema, db_schema):
    """
    Both are lists of {column, datatype, length}
    """
    f_map = {c["column"].lower(): c for c in file_schema}
    d_map = {c["column"].lower(): c for c in db_schema}
    missing, extra, mismatch = [], [], []
    for col in f_map:
        if col not in d_map:
            missing.append(f_map[col]["column"])
        else:
            ft = normalize_type_for_compare(f_map[col].get("datatype") or f_map[col].get("type"))
            dt = normalize_type_for_compare(d_map[col].get("datatype") or d_map[col].get("type"))
            if ft != dt:
                mismatch.append({
                    "column": f_map[col]["column"],
                    "file_type": f_map[col].get("datatype") or f_map[col].get("type"),
                    "db_type": d_map[col].get("datatype") or d_map[col].get("type")
                })
    for col in d_map:
        if col not in f_map:
            extra.append(d_map[col]["column"])
    ok = not (missing or mismatch)
    return {"ok": ok, "missing_in_db": missing, "extra_in_db": extra, "type_mismatches": mismatch}


# -------------------------
# DDL & Upsert
def create_table_ddl(cursor, table_name, schema):
    col_defs = []
    pk_cols = []
    numeric_pk_cols = []

    # collect PK columns and numeric PKs
    for col in schema:
        name = col["column"]
        datatype = (col.get("datatype") or col.get("type") or "VARCHAR").upper()

        # base dt
        if datatype in ("INT", "INTEGER"):
            dt = "INT"
        elif datatype == "BIGINT":
            dt = "BIGINT"
        elif datatype.startswith("DECIMAL"):
            dt = datatype
        elif datatype == "DATE":
            dt = "DATE"
        elif datatype == "DATETIME":
            dt = "DATETIME"
        elif datatype == "TEXT":
            dt = "TEXT"
        elif "JSON" in datatype:
            dt = "JSON"
        elif datatype in ("BOOLEAN", "BOOL"):
            dt = "TINYINT(1) DEFAULT 0"
        else:
            length = col.get("length") or 255
            try:
                length = max(1, min(500, int(length)))
            except:
                length = 255
            dt = f"VARCHAR({length})"

        # primary handling
        if col.get("primary"):
            pk_cols.append(name)
            if dt in ("INT", "BIGINT"):
                numeric_pk_cols.append(name)

        col_defs.append(f"`{name}` {dt}")

    # -----------------------------
    # AUTO_INCREMENT RULE
    # -----------------------------
    auto_inc_col = None

    if len(pk_cols) == 1:          # only one PK allowed to use AUTO_INCREMENT
        if len(numeric_pk_cols) == 1:
            auto_inc_col = numeric_pk_cols[0]

    # build column definitions
    final_defs = []
    for cd in col_defs:
        col_name = cd.split()[0].strip("`")
        if col_name == auto_inc_col:
            cd += " AUTO_INCREMENT"
        final_defs.append(cd)
# CREATE TABLE IF NOT EXISTS `{table_name}`
    # build ddl
    ddl = f"""

    CREATE TABLE `{table_name}`(
        {", ".join(final_defs)},
        row_hash VARCHAR(64),
        PRIMARY KEY({",".join(f"`{c}`" for c in pk_cols)})
    ) ENGINE=InnoDB;
    """

    cursor.execute(ddl)


def normalize_boolean_columns(df):
    bool_map = {
        "true": 1, "false": 0,
        "yes": 1, "no": 0
    }

    for col in df.columns:
        ser = df[col].astype(str).str.lower()

        # Only convert if ALL values are boolean-like
        if ser.isin(["true", "false", "yes", "no"]).all():
            df[col] = ser.map(bool_map)

    return df



def upsert_df_to_table(cursor, table_name, df: pd.DataFrame):
    cols = df.columns.tolist()
    col_sql = ",".join([f"`{c}`" for c in cols])
    ph = ",".join(["%s"] * len(cols))
    update_sql = ", ".join([f"`{c}`=VALUES(`{c}`)" for c in cols if c != "row_hash"])
    sql = f"""
INSERT INTO `{table_name}` ({col_sql})
VALUES ({ph})
ON DUPLICATE KEY UPDATE {update_sql};
"""
    cursor.executemany(sql, df.values.tolist())
    return cursor.rowcount


def build_dataset_summary(df: pd.DataFrame):
    summary = {
        "row_count": int(len(df)),
        "column_count": int(len(df.columns)),
        "columns": {}
    }

    for col in df.columns:
        ser = df[col]

        col_summary = {
            "dtype": str(ser.dtype),
            "null_pct": round(ser.isna().mean() * 100, 2),
            "unique_count": int(ser.nunique())
        }

        if pd.api.types.is_numeric_dtype(ser):
            col_summary.update({
                "min": float(ser.min()),
                "max": float(ser.max()),
                "mean": round(float(ser.mean()), 2),
                "median": round(float(ser.median()), 2),
                "p95": round(float(ser.quantile(0.95)), 2)
            })

        elif pd.api.types.is_object_dtype(ser):
            col_summary["top_5_values"] = (
                ser.value_counts().head(5).to_dict()
            )

        summary["columns"][col] = col_summary

    return summary


def validate_insights(insights: list):
    """
    Accept only insights that contain numeric evidence
    """
    valid = []
    for ins in insights:
        if isinstance(ins, str) and any(ch.isdigit() for ch in ins):
            valid.append(ins)
    return valid


def generate_insights_from_llm(df: pd.DataFrame, file_name: str):
    try:
        summary = build_dataset_summary(df)

        # sample only for context, NOT truth
        sample = df.sample(min(50, len(df))).fillna("").to_dict(orient="records")

        prompt = f"""
You are a senior business data analyst.

Dataset: {file_name}

The statistics below are computed from the FULL dataset.
You MUST NOT guess, assume, or infer anything not present.

DATASET FACTS:
{json.dumps(summary, indent=2)}

Optional sample rows (for context only):
{json.dumps(sample, indent=2)}

STRICT RULES:
1. Every insight MUST reference at least one numeric value from DATASET FACTS
2. DO NOT use words like: appears, seems, relatively, may indicate
3. DO NOT repeat obvious facts (row count, column count)
4. Focus on anomalies, skewed distributions, risks, or business implications
5. If something cannot be concluded → OMIT it

Return ONLY a JSON array of short insights.
"""

        raw = call_llm(prompt)
        raw = raw.replace("```json", "").replace("```", "").strip()

        parsed = safe_parse_json(raw)

        if isinstance(parsed, list):
            cleaned = validate_insights([str(x) for x in parsed])
            return cleaned if cleaned else ["No statistically valid insights generated"]

        return ["[Insight Error] Invalid LLM response format"]

    except Exception as ex:
        return [f"[Insight Error] {str(ex)}"]


def fetch_existing_user_tables_with_schema(cursor, session_id, created_by):
    cursor.execute("""
        SELECT DISTINCT table_name
        FROM uploaded_files
        WHERE session_id = %s AND created_by = %s
    """, (session_id, created_by))

    tables = [r["table_name"] for r in cursor.fetchall()]
    existing_list = []
    dropdown = []

    for t in tables:
        try:
            cursor.execute(f"SHOW COLUMNS FROM `{t}`")
            cols = cursor.fetchall()

            schema = []
            for c in cols:
                col_name = c["Field"]

                #  Hide internal column
                if col_name.lower() == "row_hash":
                    continue

                type_str = c.get("Type")
                match = re.match(r"(\w+)(?:\((\d+)\))?", type_str)
                datatype = match.group(1).lower() if match else type_str
                length = int(match.group(2)) if match and match.group(2) else None

                schema.append({
                    "column": col_name,
                    "datatype": datatype,
                    "length": length,
                    "primary": c.get("Key") == "PRI"
                })

            existing_list.append({
                "table_name": t,
                "schema": schema
            })

            dropdown.append({
                "label": t,
                "value": t
            })

        except Exception:
            continue

    return {
        "existing_tables": existing_list,
        "table_dropdown": dropdown
    }

# Strict row-level validation.
    # If ANY row fails → return errors.
def validate_rows_strict(df: pd.DataFrame, schema: list):
    errors = []

    schema_map = {c["column"]: c for c in schema}

    for idx, row in df.iterrows():
        for col, rule in schema_map.items():
            val = row.get(col)

            dtype = (rule.get("datatype") or "").upper()

            # -------- NULL CHECK --------
            if rule.get("primary") and val in (None, ""):
                errors.append({
                    "row": int(idx + 1),
                    "column": col,
                    "error": "PRIMARY KEY cannot be NULL"
                })

            # -------- INT --------
            if dtype in ("INT", "INTEGER", "BIGINT"):
                if val is not None:
                    try:
                        int(val)
                    except:
                        errors.append({
                            "row": int(idx + 1),
                            "column": col,
                            "error": "Invalid integer value"
                        })

            # -------- DECIMAL / FLOAT --------
            if dtype in ("FLOAT", "DOUBLE") or dtype.startswith("DECIMAL"):
                if val is not None:
                    try:
                        float(val)
                    except:
                        errors.append({
                            "row": int(idx + 1),
                            "column": col,
                            "error": "Invalid numeric value"
                        })

            # -------- DATE --------
            if dtype == "DATE":
                if val is None:
                    errors.append({
                        "row": int(idx + 1),
                        "column": col,
                        "error": "Invalid DATE format"
                    })

        #  stop early if too many errors
        if len(errors) >= 20:
            break

    return errors

def build_validation_message(row_errors):
    if not row_errors:
        return "Validation failed."

    # collect unique error types
    columns = set()
    error_types = set()

    for err in row_errors:
        columns.add(err.get("column"))
        error_types.add(err.get("error"))

    # single column, single error
    if len(columns) == 1 and len(error_types) == 1:
        col = next(iter(columns))
        err = next(iter(error_types))
        return f"{err} found in column '{col}'. Batch aborted."

    # multiple errors
    return (
        f"Multiple validation errors found in {len(row_errors)} rows. "
        f"Batch insert/update aborted."
    )


# -------------------------
# Main single-endpoint handler
# -------------------------
def upload_and_insights_new_controller():
    try:
        # parse payload
        if request.content_type and request.content_type.startswith("multipart"):
            action = request.form.get("action")
            session_id = request.form.get("session_id")
            created_by = request.form.get("created_by")
            workspace_id = request.form.get("workspace_id")
            body = dict(request.form)
        else:
            body = request.get_json(force=True)
            action = body.get("action")
            session_id = body.get("session_id")
            created_by = body.get("created_by")
            workspace_id = body.get("workspace_id")
            # file_name may be sent for preview/insert
            file_name = body.get("file_name")

        # Sanitize workspace_id (must be a valid integer workspace ID, cannot be 'all' or empty)
        if workspace_id is not None:
            workspace_id_str = str(workspace_id).strip().lower()
            if workspace_id_str in ["", "all", "undefined", "null"]:
                workspace_id = None
            else:
                try:
                    workspace_id = int(workspace_id)
                except ValueError:
                    workspace_id = None

        if not session_id or not created_by or not workspace_id:
            return build_response(False, "session_id, created_by & a specific workspace_id are required", 400)
        
        if not hasattr(g, "company_db"):
            return build_response(False, "Invalid session", 401)

        company_db  = g.company_db
        cur = company_db.cursor(dictionary=True)
        cur.execute("SELECT user_id FROM users WHERE session_id=%s AND user_id=%s", (session_id, created_by))
        if not cur.fetchone():
            cur.close()
            return build_response(False, "Invalid session", 400)

        # --------------------------
        # ACTION: upload
        # --------------------------
        if action == "upload":
            files = request.files.getlist("files")
            if not files:
                cur.close()
                return build_response(False, "No file uploaded", 400)
            f = files[0]
            fname = secure_filename(f.filename)
            if not allowed_file(fname):
                cur.close()
                return build_response(False, "Invalid file format", 400)
            # save
            path = os.path.join(UPLOAD_FOLDER, fname)
            f.save(path)
            file_size = format_file_size(os.path.getsize(path))
            suggested_table = sanitize_table_name(fname)
           
            # robust CSV load (encoding + delimiter sniff)
            try:
                # df = pd.read_csv(path, dtype=str, encoding="utf-8-sig")
                has_header = body.get("has_header", True)

                df = load_csv(path, has_header)

                if not has_header:
                    df = apply_default_headers(df)

                df.columns = clean_column_names(df.columns)
                df = df.where(pd.notnull(df), None)

                 # --- CSV already loaded here ---
                actual_rows = df.shape[0]
                actual_columns = df.shape[1]
            except Exception:
                # try sniff delimiter
                with open(path, "r", encoding="utf-8-sig", errors="ignore") as fh:
                    sample = fh.read(4096)
                    try:
                        dialect = csv.Sniffer().sniff(sample)
                        delimiter = dialect.delimiter
                    except Exception:
                        delimiter = ','
                try:
                    df = pd.read_csv(path, dtype=str, delimiter=delimiter, encoding="utf-8-sig", on_bad_lines='skip')
                except TypeError:
                    df = pd.read_csv(path, dtype=str, delimiter=delimiter, encoding="utf-8-sig", error_bad_lines=False)

            # header cleaning: never-null names & uniqueness
            raw_cols = list(df.columns)
            cleaned_headers = clean_column_names(raw_cols)
            df.columns = cleaned_headers

            # data cleaning (keep NaN -> None)
            df = df.where(pd.notnull(df), None)

            # generate schema via LLM (safe)
            try:
                new_table_schema = infer_schema_with_llm(df, fname)
            except Exception as e:
                new_table_schema = [{"error": "schema_infer_failed", "message": str(e)}]

            # ensure no null column names
            clean_schema = []
            for i, col in enumerate(new_table_schema):
                # ensure dict
                if not isinstance(col, dict):
                    continue
                fixed = {k: to_python(v) for k, v in col.items()}
                if fixed.get("column") in [None, "", "null", "None"]:
                    # fallback to header index
                    if i < len(cleaned_headers):
                        fixed["column"] = cleaned_headers[i]
                    else:
                        fixed["column"] = f"col_{i}"
                clean_schema.append(fixed)

            # fetch existing tables for UI
            existing = fetch_existing_user_tables_with_schema(cur, session_id, created_by)

            for r in cur.stored_results():
                r.fetchone()

            company_db.commit()

            cur.close()
            return build_response(True, "File uploaded", 200, {
                "file_name": fname,
                "file_size": file_size,
                "suggested_table_name": suggested_table,
                "new_table_schema": clean_schema,
                "existing_tables": existing["existing_tables"],
                "table_dropdown": existing["table_dropdown"],
            })

        # --------------------------
        # ACTION: preview
        # --------------------------
        # --------------------------
        # ACTION: create_table
        if action == "create_table":
            file_name = body.get("file_name")
            table_name = body.get("table_name")
            schema = body.get("schema")
            has_header = body.get("has_header", True)

            if not file_name or not table_name or not schema:
                cur.close()
                return build_response(False, "file_name, table_name & schema required", 400)
            # ==============================
            # SCENARIO CHECK : TABLE EXISTS ?
            # ==============================

            # Check table exists or not
            cur.execute("""
                SELECT COUNT(*) AS cnt
                FROM information_schema.tables
                WHERE table_schema = DATABASE()
                AND table_name = %s
            """, (table_name,))

            table_exists = cur.fetchone()["cnt"] > 0

            # --------------------------------
            # IF TABLE EXISTS → CHECK SCHEMA
            # --------------------------------
            if table_exists:

                # Fetch existing table columns
                cur.execute(f"SHOW COLUMNS FROM `{table_name}`")
                existing_cols = cur.fetchall()

                existing_col_names = [
                    c["Field"].lower()
                    for c in existing_cols
                    if c["Field"].lower() != "row_hash"
                ]

                new_col_names = [
                    c["column"].lower()
                    for c in schema
                ]

                # -----------------------------
                # SCENARIO-2: SAME COLUMNS
                # -----------------------------
                if set(existing_col_names) == set(new_col_names):
                    cur.close()
                    return build_response(
                        False,
                        f"Table `{table_name}` already exists with {len(existing_col_names)} columns.",
                        409
                    )

                # -----------------------------
                # SCENARIO-3: DIFFERENT COLUMNS
                # -----------------------------
                else:
                    cur.close()
                    return build_response(
                        False,
                        f"Table `{table_name}` already exists with a different schema.",
                        409
                    )

            # --------------------------------
            # SCENARIO-1: TABLE DOES NOT EXIST
            # → CONTINUE TO CREATE TABLE
            # --------------------------------

            file_path = os.path.join(UPLOAD_FOLDER, file_name)


            # has_header = body.get("has_header", True)

            # try:
            #     validate_header_vs_table(has_header, False)
            # except ValueError as e:
            #     cur.close(); db.close()
            #     return build_response(False, str(e), 400)

            # ---- CREATE TABLE ----
            company_db = g.company_db
            cur2 = company_db.cursor()
            column_count = len(schema)

            try:
                create_table_ddl(cur2, table_name, schema)
                company_db.commit()
                # --------------------------------------
                # INSERT METADATA EVEN IF NO DATA INSERT
                # --------------------------------------
                try:
                    cur.callproc("sp_insert_uploaded_file", [
                        session_id,
                        workspace_id,
                        file_name,
                        table_name,
                        format_file_size(os.path.getsize(file_path)),              # file_size (no data yet)
                        "csv",
                        0,                 # actual_rows
                        0,                 # actual_columns
                        0,                 # total_rows
                        len(schema),       # total_columns
                        created_by,
                        "done",            # table_extraction_status
                        "done",            # column_extraction_status
                        "[]",              # insights
                        "pending",         # insights_status
                        "pending",         # data_insert_status
                        0                  # new_rows
                    ])

                    for r in cur.stored_results():
                        r.fetchone()

                    company_db.commit()

                except Exception:
                    company_db.rollback()

            except Exception as e:
                company_db.rollback()
                cur2.close()
                cur.close()
                return build_response(False, f"Create table failed: {str(e)}", 500)

            cur2.close()

            # ---- PREVIEW (same as preview action) ----
            try:
                preview_data = build_preview_response(
                    file_name=file_name,
                    table_name=table_name,
                    schema=schema,
                    is_existing=False,
                    has_header=has_header
                )
            except Exception as e:
                cur.close()
                return build_response(False, str(e), 400)

            cur.close()
            return build_response(True, "Table created & preview ready", 200, {
                **preview_data,
                # "summary_message": f"Table `{table_name}` created successfully."
                "summary_message": f"Table `{table_name}` created successfully with {column_count} columns."
            })

        # --------------------------
        # ACTION: preview
        # --------------------------
        if action == "preview":
            file_name = body.get("file_name")
            table_name = body.get("table_name")
            is_existing = bool(body.get("is_existing", False))
            schema = body.get("schema")  # only for new table

            if not file_name or not table_name:
                cur.close()
                return build_response(False, "file_name and table_name required", 400)

            path = os.path.join(UPLOAD_FOLDER, file_name)
            if not os.path.exists(path):
                cur.close()
                return build_response(False, "CSV file missing", 400)

            # --------------------------
            # LOAD CSV
            # --------------------------
            # df = pd.read_csv(path, dtype=str, encoding="utf-8-sig")
            # df.columns = clean_column_names(df.columns)
            has_header = body.get("has_header", True)

           
            # PREVIEW VALIDATION GATE
            # =========================

            # Scenario 4,6,8 → BLOCK
            if not has_header and is_existing:
                cur.close()
                return build_response(
                    False,
                    "File without header cannot be mapped to existing table",
                    400
                )

            df = load_csv(path, has_header)

            if not has_header:
                df = apply_default_headers(df)

            df.columns = clean_column_names(df.columns)
            df = df.where(pd.notnull(df), None)
            df_clean = df.drop_duplicates().dropna(how="all")
            # =========================
            # Scenario-3 validation
            # No header + New table
            # =========================
            if not has_header and not is_existing:
                # first_row = df_clean.iloc[0].astype(str).tolist()
                if df_clean.empty:
                    cur.close()
                    return build_response(False, "CSV contains no valid data rows", 400)

                first_row = df_clean.iloc[0].astype(str).tolist()

                # If header-like text found in first row → error
                if any(re.search(r"[a-zA-Z]", v) for v in first_row):
                    cur.close()
                    return build_response(
                        False,
                        "Invalid data: first row treated as data but contains header-like values",
                        400
                    )


            # =====================================================
            # CASE: NEW TABLE PREVIEW
            # =====================================================
            if not is_existing:
                if not schema:
                    cur.close()
                    return build_response(False, "Schema required for new table preview", 400)

                df_clean = align_csv_to_schema(df_clean, schema)
                df_clean = normalize_boolean_columns(df_clean)

                # preview_rows = df_clean.head(5).fillna("").to_dict(orient="records")
                preview_rows = remove_row_hash(df_clean.head(5).fillna("").to_dict(orient="records"))

                total_rows = df_clean.shape[0]

                cur.close()
                return build_response(True, "Preview", 200, {
                    "table_name": table_name,
                    "total_rows": total_rows,
                    "preview_rows": preview_rows
                })

            # =====================================================
            # CASE : EXISTING TABLE PREVIEW  
            # =====================================================
            csv_cols = [c.lower() for c in df_clean.columns]

            cur.execute(f"SHOW COLUMNS FROM `{table_name}`")
            cols = cur.fetchall()

            # Construct DB schema and columns
            db_schema = []
            db_cols = []
            allowed_missing = set()
            for c in cols:
                col_name = c["Field"]
                if col_name.lower() == "row_hash":
                    continue
                db_cols.append(col_name.lower())
                
                is_pri = c["Key"] == "PRI"
                is_auto = "auto_increment" in str(c.get("Extra", "")).lower()
                dtype = str(c["Type"]).upper()
                is_int = any(t in dtype for t in ("INT", "INTEGER", "BIGINT"))
                
                if is_pri:
                    if is_auto or not is_int:
                        allowed_missing.add(col_name.lower())
                        
                db_schema.append({
                    "column": col_name,
                    "datatype": c["Type"],
                    "primary": is_pri,
                    "extra": c.get("Extra", "")
                })

            column_count = len(db_cols)

            missing_in_csv = [c for c in db_cols if c not in csv_cols and c not in allowed_missing]
            extra_in_csv = [c for c in csv_cols if c not in db_cols]

            #  Schema mismatch
            if missing_in_csv or extra_in_csv:
                cur.close()
                return build_response(False, "Schema mismatch", 400, {
                    "missing_in_csv": missing_in_csv,
                    "extra_in_csv": extra_in_csv
                })

            # Schema OK → align and preview
            df_clean = align_csv_to_schema(df_clean, db_schema)
            df_clean = normalize_boolean_columns(df_clean)

            preview_rows = df_clean.head(5).fillna("").to_dict(orient="records")
            total_rows = df_clean.shape[0]

            cur.close()
            return build_response(True, "Table already exists.", 200, {
                "table_name": table_name,
                "total_rows": total_rows,
                "preview_rows": preview_rows,
                "summary_message": f"Table `{table_name}` already exists with {column_count} columns."
            })

        # --------------------------
        # ACTION: insert_data
        # --------------------------
        if action == "insert_data":
                file_name = body.get("file_name")
                file_name = os.path.basename(file_name)  #  ADD THIS LINE
                table_name = body.get("table_name")
                is_existing = bool(body.get("is_existing", False))
                schema = body.get("schema")  # Only required for new table creation

                if not file_name or not table_name:
                    cur.close()
                    return build_response(False, "file_name and table_name required", 400)

                # --- Load CSV ---
                path = os.path.join(UPLOAD_FOLDER, file_name)
                if not os.path.exists(path):
                    cur.close()
                    return build_response(False, "CSV file missing", 400)

                # df = pd.read_csv(path, dtype=str, encoding="utf-8-sig")
                # df.columns = clean_column_names(df.columns)
                has_header = body.get("has_header", True)
                # ================================
                #  CHUNK BASED INSERT (SAFE)
                # ================================

                CSV_CHUNK_SIZE = 10000   # 10k per batch
                company_db = g.company_db
                cur3 = company_db.cursor(dictionary=True)

                file_hash = make_file_hash(session_id, file_name)
                with open(path, "r", encoding="utf-8-sig", errors="ignore") as f:
                            estimated_total_rows = sum(1 for _ in f)
                            if has_header:
                                estimated_total_rows -= 1

    # --- INIT PROGRESS ROW ---
                cur3.execute("""
    INSERT INTO upload_progress
    (session_id, file_name, file_hash, processed_rows, total_rows, status)
    VALUES (%s, %s, %s, 0, %s, 'started')
    ON DUPLICATE KEY UPDATE
        processed_rows=0,
        total_rows=VALUES(total_rows),
        status='started',
        updated_at=NOW()
    """, (session_id, file_name, file_hash, estimated_total_rows))


                company_db.commit()
                # company_db = g.company_db
                # cur3 = company_db.cursor(dictionary=True)

    #  BEFORE INSERT COUNT
                cur3.execute(f"SELECT COUNT(*) AS cnt FROM `{table_name}`")
                before_rows = cur3.fetchone()["cnt"]

                # Ensure we have schema to align CSV columns correctly
                if not schema:
                    cur3.execute(f"SHOW COLUMNS FROM `{table_name}`")
                    cols = cur3.fetchall()
                    schema = []
                    for c in cols:
                        col_name = c["Field"]
                        if col_name.lower() == "row_hash":
                            continue
                        schema.append({
                            "column": col_name,
                            "datatype": c["Type"],
                            "primary": c["Key"] == "PRI",
                            "extra": c.get("Extra", "")
                        })

                actual_rows = 0
                actual_columns = 0
                total_rows = 0
                total_cols = 0

                try:
                    reader = load_csv(path, has_header, chunksize=CSV_CHUNK_SIZE)

                    processed_rows = 0
                    for chunk_index, df_chunk in enumerate(reader):

            # ----------------------
            # HEADER HANDLING
            # ----------------------
                        if not has_header:
                            df_chunk = apply_default_headers(df_chunk)

                        df_chunk.columns = clean_column_names(df_chunk.columns)
                        df_chunk = df_chunk.where(pd.notnull(df_chunk), None)

            # ----------------------
            # STATS (first chunk only)
            # ----------------------
                        if chunk_index == 0:
                            actual_columns = df_chunk.shape[1]

                        actual_rows += df_chunk.shape[0]

            # ----------------------
            # CLEAN & NORMALIZE
            # ----------------------
                        df_chunk = align_csv_to_schema(df_chunk, schema, drop_unmapped=True)
                        df_chunk = df_chunk.drop_duplicates().dropna(how="all")
                        df_chunk = normalize_boolean_columns(df_chunk)

                        if schema:
                            df_chunk = normalize_date_columns(df_chunk, schema)

            # ----------------------
            # ROW HASH (FAST)
            # ----------------------
                        df_chunk["row_hash"] = (
                            df_chunk.astype(str)
                            .fillna("")
                            .agg("|".join, axis=1)
                            .map(lambda x: hashlib.md5(x.encode()).hexdigest())
                        )



            # ----------------------
            # INSERT THIS CHUNK
            # ----------------------
                        upsert_df_to_table(cur3, table_name, df_chunk)
                        company_db.commit()
                        processed_rows += df_chunk.shape[0]
                        cur3.execute("""
        UPDATE upload_progress
        SET processed_rows=%s,
            status='processing',
            updated_at=NOW()
        WHERE file_hash=%s
    """, (processed_rows, file_hash))

                        total_rows += df_chunk.shape[0]
                        total_cols = len([c for c in df_chunk.columns if c.lower() != "row_hash"])

                    cur3.execute("""
    UPDATE upload_progress
    SET status='done',
        processed_rows=%s,
        updated_at=NOW()
    WHERE file_hash=%s
    """, (processed_rows, file_hash))


        #  AFTER INSERT COUNT
                    cur3.execute(f"SELECT COUNT(*) AS cnt FROM `{table_name}`")
                    after_rows = cur3.fetchone()["cnt"]

                    new_rows = max(0, after_rows - before_rows)
                    total_rows = after_rows
                    insert_status = "done"

                except Exception as e:
                    company_db.rollback()
                    insert_status = "failed"
                    cur3.close()
                    cur.close()
                    return build_response(False, f"Insert failed: {str(e)}", 500)

                # --------------------------------------
                # REFRESH QUERY ROW COUNTS (HERE)
                # --------------------------------------
                try:
                    cur3.callproc("sp_refresh_query_row_counts")
                    company_db.commit()
                except Exception as e:
                    #  data insert already successful, so don't fail main flow
                    print("Row count refresh failed:", str(e))

                # --------------------------------------
                # Generate LLM insights
                # --------------------------------------
              

                try:
                    #  use LAST chunk sample only (safe)
                    insights_list = generate_insights_from_llm(df_chunk, file_name)
                    insights_json = json.dumps(insights_list)
                    insight_status = "done"
                except:
                    insights_json = "[]"
                    insight_status = "failed"
                # --------------------------------------
                # CALL STORED PROCEDURE (metadata)
                # --------------------------------------
                try:
                    cur3.callproc("sp_insert_uploaded_file", [
                        session_id,
                        workspace_id,
                        file_name,
                        table_name,
                        format_file_size(os.path.getsize(path)),
                        "csv",
                        actual_rows,          #  NEW
                        actual_columns, 
                        total_rows,
                        total_cols,
                        created_by,
                        "done",
                        "done",
                        insights_json,
                        insight_status,
                        insert_status,
                        new_rows  
                    ])

                    sp_result = None
                    for r in cur3.stored_results():
                        row = r.fetchone()
                        if row:
                            sp_result = row
                            break

                    if sp_result and isinstance(sp_result, dict):
                        file_id = sp_result.get("file_id")
                        status_flag = sp_result.get("status_flag")
                    else:
                        file_id = None
                        status_flag = "UNKNOWN"

                    company_db.commit()

                    # --------------------------------------
                    # INGEST INTO RAG (Vector + MySQL)
                    # --------------------------------------
                    try:
                        from helper.rag_ingestion import ingest_uploaded_csv
                        ingest_uploaded_csv(company_db.database, session_id, path, workspace_id)
                    except Exception as e:
                        print(f"RAG CSV Ingestion Error: {e}")

                except Exception as e:
                    print(f"CRITICAL ERROR in sp_insert_uploaded_file: {str(e)}")
                    company_db.rollback()
                    cur3.close()
                    cur.close()
                    return build_response(False, f"Procedure failed: {str(e)}", 500)

                cur3.close()
                cur.close()
                if not is_existing:
                    summary_message = (
                        f"Table `{table_name}` successfully created with "
                        f"{total_cols} columns and {total_rows} rows."
                    )
                else:
                    if new_rows > 0:
                        summary_message = (
                            f"Table `{table_name}` successfully updated with {total_cols} columns. "
                            f"{new_rows} new rows added, total rows now {total_rows}."
                        )
                    else:
                        summary_message = (
                            f"Table `{table_name}` already exists with {total_cols} columns. "
                            f"No new data was available to insert; total rows remain {total_rows}."
                        )


                return build_response(True, "Data inserted", 200, {
                    "file_id": file_id,
                    "file_status": status_flag,
                    "table_name": table_name,
                    "total_rows": total_rows,
                    "total_columns": total_cols,
                    "summary_message": summary_message
                })


            # unknown action
        
        cur.close()
        return build_response(False, "Unknown action", 400)

    except Exception as ex:
        try:
            company_db.rollback()
        except Exception:
            pass
        return build_response(False, "Server error", 500, {"error": str(ex)})
  

# get_upload_progress_controller
def get_upload_progress_controller():
    data = request.get_json(force=True)
    session_id = data.get("session_id")
    file_name = data.get("file_name")

    file_hash = make_file_hash(session_id, file_name)

    cur = g.company_db.cursor(dictionary=True)
    cur.execute("""
        SELECT processed_rows, total_rows, status
        FROM upload_progress
        WHERE file_hash=%s
    """, (file_hash,))

    row = cur.fetchone()
    cur.close()

    if not row:
        return build_response(False, "No progress found", 404)

    percent = 0
    if row["total_rows"] > 0:
        percent = round(
            (row["processed_rows"] / row["total_rows"]) * 100, 2
        )

    return build_response(True, "Progress", 200, {
        **row,
        "percent": percent
    })