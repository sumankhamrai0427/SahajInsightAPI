import json
from flask import g
from model.llm_client import call_llm

NUMERIC_TYPES = {"int", "bigint", "decimal", "float", "double"}
DATE_TYPES = {"date", "datetime", "timestamp"}
TEXT_TYPES = {"varchar", "text", "char"}

def is_id_column(column_name: str) -> bool:
    col = column_name.lower()
    return (
        col == "id"
        or col.endswith("_id")
        or col.endswith("id")
    )

def get_column_types(table_name):
    """
    Fetch exact column datatypes from MySQL (BEST PRACTICE)
    """
    conn = g.company_db
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = DATABASE()
          AND table_name = %s
    """, (table_name,))

    rows = cursor.fetchall()
    cursor.close()

    # return {r["column_name"]: r["data_type"].lower() for r in rows}
    return {
    r.get("column_name") or r.get("COLUMN_NAME"):
        (r.get("data_type") or r.get("DATA_TYPE")).lower()
    for r in rows
    }


def aggregation_support(col_type):
    if col_type in NUMERIC_TYPES:
        return ["min", "max", "sum", "avg", "count"]
    if col_type in DATE_TYPES:
        return ["min", "max", "count"]
    return ["count"]


def group_filter_support(col_type):
    if col_type in TEXT_TYPES:
        return {
            "group_by": True,
            "filter": ["equals", "in", "like"]
        }
    if col_type in DATE_TYPES:
        return {
            "group_by": True,
            "filter": ["between", "before", "after"]
        }
    if col_type in NUMERIC_TYPES:
        return {
            "group_by": False,
            "filter": ["=", ">", "<", "between"]
        }
    return {}

def is_groupby_allowed(column_name: str, column_type: str) -> bool:
    # ID column group by 
    if is_id_column(column_name):
        return False

    #  Numeric column group by 
    if column_type in NUMERIC_TYPES:
        return False

    # Text / Date column group by
    if column_type in TEXT_TYPES or column_type in DATE_TYPES:
        return True

    return False



def suggest_charts_llm(column_meta):
    prompt = f"""
You are a senior data visualization expert.

Dataset columns with types:
{json.dumps(column_meta, indent=2)}

Return ONLY JSON:
{{
  "possible_charts": ["bar","pie","bubble","mixed","box","waterfall","kpi"]
}}
"""
    try:
        res = call_llm(prompt)

        #  VERY IMPORTANT: clean LLM response
        res = res.replace("```json", "").replace("```", "").strip()

        return json.loads(res)
    except Exception:
        return {"possible_charts": ["bar"]}

def build_insights(table_name, columns):
    col_types = get_column_types(table_name)

    aggregations = {}
    group_by = []
    filters = {}

    for col in columns:

        # BLOCK ID COLUMNS
        if is_id_column(col):
            continue

        ctype = col_types.get(col)
        if not ctype:
            continue

        # aggregation support
        aggregations[col] = aggregation_support(ctype)

        #  FIXED GROUP BY RULE
        if is_groupby_allowed(col, ctype):
            group_by.append(col)

        gf = group_filter_support(ctype)
        if gf.get("filter"):
            filters[col] = gf["filter"]

    charts = suggest_charts_llm(col_types)

    return {
        "column_types": col_types,
        "aggregations": aggregations,
        "group_by": sorted(group_by, key=str.lower),
        "filters": filters,
        "charts": charts
    }
    
    
    

