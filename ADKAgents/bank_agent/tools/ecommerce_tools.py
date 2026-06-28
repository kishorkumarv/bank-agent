import os

from dotenv import load_dotenv
from google.cloud import bigquery

from ..observability.tool_tracer import traced_tool

load_dotenv()

PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "")
ECOMMERCE_DATASET = os.getenv("ECOMMERCE_DATASET", "ecommerce_data")


def _bq_client() -> bigquery.Client:
    return bigquery.Client(project=PROJECT_ID if PROJECT_ID else None)


@traced_tool
def lookup_user_orders(email: str) -> str:
    """Retrieves a user's order history using their email address.

    Args:
        email: The email address of the user.

    Returns:
        A string representation of the user's recent orders or an error message.
    """
    try:
        client = _bq_client()
        query = f"""
            SELECT o.order_id, o.order_date, p.name as product_name, o.quantity, p.price, o.status
            FROM `{ECOMMERCE_DATASET}.users` u
            JOIN `{ECOMMERCE_DATASET}.orders` o ON u.user_id = o.user_id
            JOIN `{ECOMMERCE_DATASET}.products` p ON o.product_id = p.product_id
            WHERE u.email = @email
            ORDER BY o.order_date DESC
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("email", "STRING", email)]
        )
        result_df = client.query(query, job_config=job_config).to_dataframe()

        if result_df.empty:
            return f"No orders found for user with email {email}."

        return result_df.to_string(index=False)
    except Exception as e:
        return f"Database Error: {str(e)}"


@traced_tool
def check_product_stock(product_name: str) -> str:
    """Checks the inventory levels and details for a specific product.

    Args:
        product_name: The name of the product to check.

    Returns:
        A string containing product details including stock level, or an error message.
    """
    try:
        client = _bq_client()
        query = f"""
            SELECT product_id, name, category, price, stock
            FROM `{ECOMMERCE_DATASET}.products`
            WHERE LOWER(name) LIKE CONCAT('%', LOWER(@product_name), '%')
        """
        job_config = bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("product_name", "STRING", product_name)]
        )
        result_df = client.query(query, job_config=job_config).to_dataframe()

        if result_df.empty:
            return f"No product found matching '{product_name}'."

        return result_df.to_string(index=False)
    except Exception as e:
        return f"Database Error: {str(e)}"


@traced_tool
def sales_reporting_query(sql: str) -> str:
    """Executes a read-only SQL query against the ecommerce dataset.

    Use this tool for analytics or reporting questions like finding top
    selling products or total revenue. Use {ecommerce_dataset} as a
    placeholder for the dataset name and it will be substituted automatically.

    The ecommerce dataset contains:
      - users (user_id, name, email, signup_date)
      - products (product_id, name, category, price, stock)
      - orders (order_id, user_id, product_id, quantity, order_date, status)

    Args:
        sql: A valid GoogleSQL SELECT statement.

    Returns:
        A plain-text table of results, or an error message.
    """
    normalised = sql.strip().upper()
    for disallowed in ("INSERT", "UPDATE", "DELETE", "DROP", "TRUNCATE", "MERGE", "CREATE", "ALTER", "GRANT", "REVOKE"):
        if normalised.startswith(disallowed):
            return "ERROR: Write operations are not permitted. Only SELECT queries are allowed."

    try:
        client = _bq_client()
        resolved_sql = sql.replace("{ecommerce_dataset}", ECOMMERCE_DATASET)
        print(f"Running ecommerce query:\n{resolved_sql}")
        result_df = client.query(resolved_sql).to_dataframe()

        if result_df.empty:
            return "Query returned no results."

        return result_df.to_string(index=False)
    except Exception as e:
        return f"BigQuery Error: {str(e)}"
