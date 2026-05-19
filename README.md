
**Local Installation Guide**

This guide explains how to run CivicMind locally, including backend setup, model configuration, and Chrome extension installation.

**1. Project Structure**

The project has two main parts:

- `CivicMind/`  
  The Chrome extension frontend

- `clearlens-backend/`  
  The FastAPI backend that calls Gemma through either Google Cloud Vertex AI or local Ollama

**2. Prerequisites**

Make sure you have these installed:

- Python 3.10+  
- Google Chrome
- `git`
- For local model mode: `Ollama`
- For cloud model mode: `gcloud` CLI and a Google Cloud project

**3. Clone or Open the Project**

```bash
cd /path/to/your/workspace
```

If needed, place the project folders like this:

```bash
CivicMind/
clearlens-backend/
```

**4. Backend Setup**

Go to the backend directory:

```bash
cd clearlens-backend
```

Create a virtual environment:

```bash
python3 -m venv .venv
```

Activate it:

```bash
source .venv/bin/activate
```

Install dependencies:

```bash
python -m pip install -r requirements.txt
```

Create the environment file:

```bash
cp .env.example .env
```

**5. Choose a Model Runtime**

CivicMind supports two backend modes:

- `vertex_ai`
- `ollama`

### Option A: Local Ollama Mode

This is the easiest option for local testing.

Install or start Ollama, then make sure a Gemma model is available.

Example:

```bash
ollama pull gemma4:e4b
```

Edit `.env` like this:

```env
LLM_PROVIDER=ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=gemma4:e4b
GOOGLE_AUTH_TIMEOUT_SECONDS=8
CLEARLENS_MAX_ANALYSIS_ATTEMPTS=3
```

Start Ollama if it is not already running.

Then start the backend:

```bash
./.venv/bin/python -m uvicorn main:app --reload
```

### Option B: Google Cloud Vertex AI Mode

Use this if you want Gemma running through Google Cloud.

Edit `.env` like this:

```env
LLM_PROVIDER=vertex_ai
GOOGLE_CLOUD_PROJECT=your-project-id
VERTEX_AI_LOCATION=your-region
VERTEX_AI_ENDPOINT=projects/your-project-id/locations/your-region/endpoints/your-endpoint-id
VERTEX_AI_PREDICTION_HOST=
GOOGLE_AUTH_TIMEOUT_SECONDS=8
CLEARLENS_MAX_ANALYSIS_ATTEMPTS=3
```

If required, authenticate locally:

```bash
gcloud auth application-default login
gcloud auth application-default set-quota-project your-project-id
```

Then start the backend:

```bash
./.venv/bin/python -m uvicorn main:app --reload
```

**6. Verify the Backend**

Once the server is running, test the health endpoint:

```bash
curl http://localhost:8000/health
```

You should see a JSON response showing the active provider, such as:

```json
{
  "status": "ok",
  "llm_provider": "ollama"
}
```

or

```json
{
  "status": "ok",
  "llm_provider": "vertex_ai"
}
```

**7. Install the Chrome Extension Locally**

Open Chrome and go to:

```text
chrome://extensions
```

Then:

1. Turn on `Developer mode`
2. Click `Load unpacked`
3. Select the `CivicMind` folder

The extension should now appear in Chrome.

**8. Configure the Extension Backend URL**

After loading the extension:

1. Open the CivicMind extension settings page
2. Set the backend URL

For local development, use:

```text
http://localhost:8000
```

If your backend is deployed remotely, enter the Cloud Run or hosted backend URL instead.

**9. Test the Extension**

1. Open a political news article in Chrome
2. Click the CivicMind extension icon
3. Wait for the sidebar to appear
4. Review the three sections:
   - `Partisan Framing`
   - `Missing Context`
   - `Cross-Party Perspective`

**10. Common Troubleshooting**

If the extension does not work:

- Make sure the backend is running on the correct URL
- Make sure the extension settings point to the correct backend URL
- If using Ollama, make sure the Ollama server is running and the model is installed
- If using Vertex AI, make sure your project, endpoint, region, and credentials are configured correctly

Backend health check:

```bash
curl http://localhost:8000/health
```

If needed, restart the backend:

```bash
./.venv/bin/python -m uvicorn main:app --reload
```

**11. Summary**

Local setup consists of:

1. installing Python dependencies
2. choosing either `ollama` or `vertex_ai`
3. starting the FastAPI backend
4. loading `CivicMind` as an unpacked Chrome extension
5. pointing the extension to the backend URL

If you want, I can also turn this into a ready-to-paste `README.md` file and write it directly into the project.
