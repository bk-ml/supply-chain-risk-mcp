from dotenv import load_dotenv
load_dotenv()

from google.genai import Client
import os

client = Client(api_key=os.environ["GEMINI_API_KEY"])
response = client.models.generate_content(
    model="gemini-3.6-flash",
    contents="Say hello in exactly 3 words.",
)
print(response.text)