import os
from dotenv import load_dotenv
from google import genai

load_dotenv()

api_key = os.getenv("GEMINI_API_KEY")
b2_key = os.getenv("B2_APPLICATION_KEY")
if not b2_key:
    raise ValueError("B2_APPLICATION_KEY environment variable is not set.")
if not api_key:
    raise ValueError("GEMINI_API_KEY environment variable is not set.")
client = genai.Client(api_key=api_key)

response = client.models.generate_content(
    model="gemini-3-flash-preview", contents="Explain how AI works in a few words"
)
print(response.text)