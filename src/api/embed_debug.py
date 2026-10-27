import os
from dotenv import load_dotenv
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from azure.ai.projects import AIProjectClient
from openai import OpenAI

load_dotenv(override=True)
ep = os.environ["FOUNDRY_PROJECT_ENDPOINT"]
model = os.environ["EMBED_DEPLOYMENT"]
cred = DefaultAzureCredential()

def try_embed(label, client):
    try:
        r = client.embeddings.create(model=model, input="test")
        print(label, "OK, length", len(r.data[0].embedding))
    except Exception as e:
        resp = getattr(e, "response", None)
        print(label, "FAILED:", type(e).__name__,
              getattr(e, "status_code", ""),
              getattr(getattr(e, "request", None), "url", ""),
              resp.text if resp is not None else e)

try_embed("A project route:",
          AIProjectClient(endpoint=ep, credential=cred).get_openai_client())

resource = ep.split("/api/projects")[0]
token = get_bearer_token_provider(cred, "https://cognitiveservices.azure.com/.default")
try_embed("B resource route:",
          OpenAI(base_url=resource + "/openai/v1/", api_key=token))