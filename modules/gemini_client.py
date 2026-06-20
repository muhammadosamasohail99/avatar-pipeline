from google import genai
from config import Settings

_client: genai.Client | None = None


def get_client() -> genai.Client:
    global _client
    if _client is None:
        _client = genai.Client(api_key=Settings().gemini_api_key)
    return _client


def generate(prompt: str) -> str:
    s = Settings()
    r = get_client().models.generate_content(model=s.gemini_model, contents=prompt)
    return r.text
