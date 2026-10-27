import os
from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from azure.ai.projects import AIProjectClient
from openai import OpenAI

load_dotenv(override=True)

_cred = DefaultAzureCredential()
_endpoint = os.environ["FOUNDRY_PROJECT_ENDPOINT"]

CHAT_DEPLOYMENT = os.environ["CHAT_DEPLOYMENT"]
EMBED_DEPLOYMENT = os.environ["EMBED_DEPLOYMENT"]


def chat_client():
    """Chat works on the project route."""
    return AIProjectClient(endpoint=_endpoint, credential=_cred).get_openai_client()


def embed_client():
    """Embeddings work on the resource route."""
    resource = _endpoint.split("/api/projects")[0]
    token = get_bearer_token_provider(_cred, "https://cognitiveservices.azure.com/.default")
    return OpenAI(base_url=resource + "/openai/v1/", api_key=token)
