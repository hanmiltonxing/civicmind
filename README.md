How Users Deploy CivicMind

Users can deploy CivicMind in two main ways: local deployment or cloud deployment.

1. Local Deployment

Backend setup:

cd clearlens/clearlens-backend
python3 -m venv .venv
./.venv/bin/python -m pip install -r requirements.txt
cp .env.example .env
For local Ollama mode:

LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=gemma4:e4b
Start the backend:

./.venv/bin/python -m uvicorn main:app --reload
For Vertex AI mode:

LLM_PROVIDER=vertex_ai
GOOGLE_CLOUD_PROJECT=your-project-id
VERTEX_AI_LOCATION=your-region
VERTEX_AI_ENDPOINT=projects/your-project-id/locations/your-region/endpoints/your-endpoint-id
VERTEX_AI_PREDICTION_HOST=your-dedicated-host-if-needed
If using Vertex AI locally, authenticate first:

gcloud auth application-default login
gcloud auth application-default set-quota-project your-project-id
Chrome extension setup:

Open chrome://extensions
Enable Developer mode
Click Load unpacked
Select the CivicMind folder
Open the extension settings page and confirm the backend URL, usually http://localhost:8000
After that, open a political article and click the CivicMind icon.
