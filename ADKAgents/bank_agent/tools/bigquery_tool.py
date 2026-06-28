import os

from dotenv import load_dotenv
from google.cloud import bigquery

from ..observability.tool_tracer import traced_tool

load_dotenv()

PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "")
BQ_DATASET = os.getenv("BQ_DATASET", "")
ECOMMERCE_DATASET = os.getenv("ECOMMERCE_DATASET", "ecommerce_data")


@traced_tool
def run_bigquery_query(sql: str) -> str:
    """Executes a read-only SQL query against BigQuery and returns the results.

    Use this tool for analytics or reporting questions. You can query any 
    project and dataset your service account has access to by using fully 
    qualified table names (e.g., `project.dataset.table`) in the SQL.
    
    Placeholders in the SQL are substituted automatically:
      - `{dataset}` → BQ_DATASET (bank dataset)
      - `{ecommerce_dataset}` → ECOMMERCE_DATASET

    Args:
        sql: A valid GoogleSQL SELECT statement.

    Returns:
        A plain-text table of results, or an error message if the query fails.
    """
    # Reject anything that looks like a write operation — this tool is read-only.
    normalised = sql.strip().upper()
    for disallowed in ("INSERT", "UPDATE", "DELETE", "DROP", "TRUNCATE", "MERGE", "CREATE", "ALTER", "GRANT", "REVOKE"):
        if normalised.startswith(disallowed):
            return f"ERROR: Write operations are not permitted. Only SELECT queries are allowed."

    try:
        # If PROJECT_ID is empty, it falls back to the default credential project
        client = bigquery.Client(project=PROJECT_ID if PROJECT_ID else None)

        resolved_sql = sql.replace("{dataset}", BQ_DATASET).replace("{ecommerce_dataset}", ECOMMERCE_DATASET)

        print(f"Running BigQuery query:\n{resolved_sql}")
        result_df = client.query(resolved_sql).to_dataframe()

        if result_df.empty:
            return "Query returned no results."

        return result_df.to_string(index=False)

    except Exception as e:
        return f"BigQuery Error: {str(e)}"
