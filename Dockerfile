# Container image for the Claims & Policy Copilot API.
FROM python:3.11-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONUTF8=1

# Install packages first so Docker can cache this layer between builds.
COPY requirements-api.txt .
RUN pip install --no-cache-dir -r requirements-api.txt

# Application code and the pre-built clause index (synthetic data only).
COPY src/api ./src/api
COPY data/processed/chunks_embedded.json data/processed/embeddings.npy ./data/processed/

EXPOSE 8000

# No settings or keys are baked into the image. They are supplied at run time
# as environment variables (FOUNDRY_PROJECT_ENDPOINT, CHAT_DEPLOYMENT, ...).
CMD ["uvicorn", "--app-dir", "src/api", "main:app", "--host", "0.0.0.0", "--port", "8000"]
