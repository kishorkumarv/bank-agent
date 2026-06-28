import os
import sqlite3

import pandas as pd
from dotenv import load_dotenv
from google.adk.tools.tool_context import ToolContext
from google.cloud import bigquery

from ..observability.tool_tracer import traced_tool

load_dotenv()

BQ_DATASET = os.getenv("BQ_DATASET", "")
PROJECT_ID = os.getenv("GOOGLE_CLOUD_PROJECT", "")



def _bq_client() -> bigquery.Client:
    return bigquery.Client(project=PROJECT_ID if PROJECT_ID else None)


@traced_tool
def customer_id_search(customer_id: str, tool_context: ToolContext) -> dict:
    """Retrieves customer information for a particular customer ID, used for verifying identity.

    Args:
        customer_id (str): The customer ID for the customer who to verify
        tool_context: provides the state of verification

    Returns:
        dict: status and result or error msg.
    """
    try:
        # SECURITY CHECK: Ensure identity is verified
        if tool_context.state.get("identity_verified") and customer_id != tool_context.state.get("verified_customer_id"):
            tool_context.state["verified_customer_id"] = ""
            tool_context.state["identity_verified"] = False
            return {"status": "error", "error_message": "Customer identity is not the same as verified. Verify the customer again"}
        elif tool_context.state.get("identity_verified") and customer_id == tool_context.state.get("verified_customer_id"):
            verified_id = tool_context.state.get("verified_customer_id")
        else:
            tool_context.state["identity_verified"] = False
            verified_id = customer_id

        print(f"Customer ID searched: {verified_id}")

        if BQ_DATASET:
            print("Pulling customer details from BigQuery")
            client = _bq_client()
            query = f"""
                SELECT customer_id, name, dob, postcode
                FROM `{BQ_DATASET}.customers`
                WHERE customer_id = @customer_id
            """
            job_config = bigquery.QueryJobConfig(
                query_parameters=[bigquery.ScalarQueryParameter("customer_id", "STRING", verified_id)]
            )
            result_df = client.query(query, job_config=job_config).to_dataframe()

            if result_df.empty:
                return {"status": "error", "error_message": "no values returned for customer ID"}

            result = result_df.iloc[0].to_dict()
        else:
            conn = sqlite3.connect("bank_data.db")
            query = """
                SELECT customer_id, name, dob, postcode
                FROM customers
                WHERE customer_id = ?
            """
            result_df = pd.read_sql_query(query, conn, params=[verified_id])
            conn.close()

            if result_df.empty:
                return {"status": "error", "error_message": "no values returned for customer ID"}

            result = result_df.iloc[0].to_dict()

        tool_context.state["identity_verified"] = True
        tool_context.state["verified_customer_id"] = verified_id
        result["status"] = "success"
        return result

    except Exception as e:
        return {"status": "error", "error_message": f"Database Error: {str(e)}"}


@traced_tool
def customer_database_search(tool_context: ToolContext) -> str:
    """
    Retrieves the currently verified customer's profile and recent financial activity.
    This tool requires no arguments as it uses the ID from the verified session context.
    tool_context: provides the state of verification
    """
    try:
        if not tool_context.state.get("identity_verified"):
            return "ERROR: Customer identity has not been verified. Please verify the customer before searching records."

        verified_id = tool_context.state.get("verified_customer_id")

        if not verified_id:
            return "ERROR: Session error. Identity verified but no Customer ID found in context."

        if BQ_DATASET:
            print("Pulling customer records from BigQuery")
            client = _bq_client()
            query = f"""
                SELECT
                    c.address, c.age, c.customer_id, c.dob, c.gender, c.name, c.phone, c.postcode,
                    a.product_type, a.balance,
                    t.description, t.amount, t.type, t.date
                FROM `{BQ_DATASET}.customers` c
                JOIN `{BQ_DATASET}.accounts` a ON c.customer_id = a.customer_id
                LEFT JOIN `{BQ_DATASET}.transactions` t ON a.account_id = t.account_id
                WHERE c.customer_id = @customer_id
                ORDER BY t.date DESC
                LIMIT 200
            """
            job_config = bigquery.QueryJobConfig(
                query_parameters=[bigquery.ScalarQueryParameter("customer_id", "STRING", verified_id)]
            )
            result_df = client.query(query, job_config=job_config).to_dataframe()
        else:
            conn = sqlite3.connect("bank_data.db")
            query = """
                SELECT
                    c.address, c.age, c.customer_id, c.dob, c.gender, c.name, c.phone, c.postcode,
                    a.product_type, a.balance,
                    t.description, t.amount, t.type, t.date
                FROM "customers" c
                JOIN "accounts" a ON c.customer_id = a.customer_id
                LEFT JOIN "transactions" t ON a.account_id = t.account_id
                WHERE c.customer_id = ?
                ORDER BY t.date DESC
                LIMIT 200;
            """
            result_df = pd.read_sql_query(query, conn, params=[verified_id])
            conn.close()

        if result_df.empty:
            return "ERROR: No record found for this Customer ID."

        return result_df.to_string(index=False)

    except Exception as e:
        return f"Database Error: {str(e)}"
