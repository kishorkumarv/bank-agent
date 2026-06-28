import os

import vertexai
from google.cloud import discoveryengine_v1beta as discoveryengine
from vertexai.generative_models import GenerativeModel
from dotenv import load_dotenv

from ..observability.tool_tracer import traced_tool

load_dotenv()
PROJECT_ID = os.environ.get("GOOGLE_CLOUD_PROJECT")
DATA_STORE_ID = os.environ.get("VERTEX_DATA_STORE_ID")
vertexai.init(project=f"{PROJECT_ID}", location="us-central1")

@traced_tool
def vertex_vector_search(query: str) -> str:
    """
    Retrieves information from Lloyds Bank and provides a summarized
    response with direct source links for transparency.
    """
    print(f"DEBUG: Project ID is {PROJECT_ID} and DATA_STORE_ID is {DATA_STORE_ID}")
    try:
        # Step 1: Build the search request
        client = discoveryengine.SearchServiceClient()

        serving_config = f"projects/{PROJECT_ID}/locations/global/collections/default_collection/engines/{DATA_STORE_ID}/servingConfigs/default_config"
        print(f"DEBUG: serving_config ID is {serving_config}")

        content_search_spec = discoveryengine.SearchRequest.ContentSearchSpec(
            extractive_content_spec=discoveryengine.SearchRequest.ContentSearchSpec.ExtractiveContentSpec(
                max_extractive_answer_count=3,
                max_extractive_segment_count=10
            ),
            summary_spec=discoveryengine.SearchRequest.ContentSearchSpec.SummarySpec(
                summary_result_count=5,
                include_citations=True,
                use_semantic_chunks=True
            )
        )

        request = discoveryengine.SearchRequest(
            serving_config=serving_config,
            query=query,
            page_size=10,
            content_search_spec=content_search_spec
        )

        # Step 2: Execute the search and extract text segments from each result
        response = client.search(request)

        context_blocks = []
        for result in response.results:
            data = result.document.derived_struct_data
            link = data.get('link', 'https://www.lloydsbank.com')

            # Enterprise tier returns extractive_segments; fall back to snippets otherwise
            segments = data.get('extractive_segments', [])
            text_for_link = " ".join([s.get('content', '') for s in segments])

            if not text_for_link:
                snippets = data.get('snippets', [])
                text_for_link = " ".join([s.get('snippet', '') for s in snippets])

            if text_for_link:
                context_blocks.append(f"SOURCE: {link}\nCONTENT: {text_for_link}")

        if not context_blocks:
            return "No official Lloyds Bank data found for this query."

        full_context = "\n\n---\n\n".join(context_blocks)

        # Step 3: Generate a grounded answer using Gemini with the retrieved context
        model = GenerativeModel("gemini-2.5-flash")

        prompt = f"""
                You are a Lloyds Bank Virtual Assistant. Using the provided context, answer the question: '{query}'.

                RULES:
                1. Only use the information provided in the context. Be precise with numbers and rates. Do not create new product names than what is offered.
                2. Keep the tone professional, helpful, and "on-brand" for a bank.
                3. At the end of your answer, provide a 'Sources' section listing the unique URLs used.
                4. If the context doesn't contain the answer, politely state that you couldn't find those specific details.

                CONTEXT FROM LLOYDS WEBSITE:
                {full_context}
                """

        summary = model.generate_content(prompt)
        return summary.text

    except Exception as e:
        return f"Search Error: {str(e)}"