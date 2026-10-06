import os
import time

from google import genai
from google.genai import errors, types

EMBEDDING_MODEL = "gemini-embedding-001"
EMBEDDING_DIMENSIONS = 768

def make_genai_client() -> genai.Client | None:
    """The Gemini client for ingest, or None when SKIP_EMBEDDINGS=1.

    With None, participants are written without an embedding and Gemini is never
    called, so GEMINI_API_KEY isn't read. Backfill later with
    `jobs.load_gcs_matches --reload`.
    """
    if os.getenv("SKIP_EMBEDDINGS") == "1":
        return None
    return genai.Client(api_key=os.environ["GEMINI_API_KEY"])


# (champion api name, star level, item api names)
Unit = tuple[str, int, list[str]]


def get_embeddings(
    client: genai.Client,
    compositions: list[tuple[list[Unit], list[str]]],
    max_retries: int = 5,
) -> list[list[float]]:
    """Embed several (units, traits) compositions in a single request.

    Returns one 768-dim vector per composition, in input order.
    """
    contents = [
        prepare_query_and_string(composition_string(units, traits))
        for units, traits in compositions
    ]
    delay = 2
    for attempt in range(max_retries):
        try:
            response = client.models.embed_content(
                model=EMBEDDING_MODEL,
                contents=contents,
                config=types.EmbedContentConfig(
                    output_dimensionality=EMBEDDING_DIMENSIONS
                ),
            )
            return [embedding.values for embedding in response.embeddings]
        except errors.APIError as exc:
            if exc.code in (429, 500, 503) and attempt < max_retries - 1:
                print(
                    f"Gemini returned {exc.code}, retrying in {delay}s (attempt {attempt + 1}/{max_retries})"
                )
                time.sleep(delay)
                delay = min(delay * 2, 60)
                continue
            raise
    raise RuntimeError(f"All {max_retries} embedding retries exhausted")


def get_embedding(
    api_key: str, participant_units: list[Unit], participant_traits: list[str]
):
    client = genai.Client(api_key=api_key)
    return get_embeddings(client, [(participant_units, participant_traits)])[0]


def unit_string(champion: str, star: int, items: list[str]) -> str:
    text = f"{champion}*{star}"
    if items:
        text += f" [{', '.join(sorted(items))}]"
    return text


def composition_string(units: list[Unit], traits: list[str]) -> str:
    unit_text = ", ".join(sorted(unit_string(*unit) for unit in units))
    return unit_text + " | " + ", ".join(sorted(traits))


# We are using the clustering task
def prepare_query_and_string(string: str):
    return f"task: clustering | query: {string}"
