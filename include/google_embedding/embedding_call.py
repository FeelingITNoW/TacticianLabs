import os
from google import genai

api_key = os.getenv("GEMINI_API_KEY")
if not api_key:
    raise ValueError("GEMINI_API_KEY environment variable is not set.")

client = genai.Client(api_key=api_key)


def get_embedding(api_key: str, participant_units: list, participant_traits: list):
    client = genai.Client(api_key=api_key)
    units_str = ", ".join(sorted(participant_units))
    traits_str = ", ".join(sorted(participant_traits))
    composition_str = units_str + " | " + traits_str
    prepped_string = prepare_query_and_string(composition_str)
    response = client.models.embed_content(
        model="gemini-embedding-001", contents=prepped_string
    )
    return response.embedding


# We are using the clustering task
def prepare_query_and_string(string: str):
    return f"task: clustering | query: {string}"
