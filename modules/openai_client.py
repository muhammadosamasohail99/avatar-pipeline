from openai import AzureOpenAI
from config import Settings


def get_azure_client() -> AzureOpenAI:
    s = Settings()
    return AzureOpenAI(
        api_key=s.azure_openai_api_key,
        azure_endpoint=s.azure_openai_endpoint,
        api_version=s.azure_openai_api_version,
    )
