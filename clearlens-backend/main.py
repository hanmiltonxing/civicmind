import asyncio
import json
import os
from pathlib import Path
import re
from typing import Any, Awaitable, Callable

import google.auth
import httpx
import requests
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from google.auth.exceptions import DefaultCredentialsError
from google.auth.transport.requests import Request as GoogleAuthRequest
from pydantic import BaseModel, Field

load_dotenv()

VERTEX_SCOPES = ["https://www.googleapis.com/auth/cloud-platform"]
DEFAULT_ALLOWED_ORIGINS = ["*"]
DEFAULT_LOCATION = "us-central1"
DEFAULT_MAX_INPUT_CHARS = 8000
DEFAULT_AUTH_TIMEOUT_SECONDS = int(os.getenv("GOOGLE_AUTH_TIMEOUT_SECONDS", "8"))
DEFAULT_MAX_ANALYSIS_ATTEMPTS = int(os.getenv("CLEARLENS_MAX_ANALYSIS_ATTEMPTS", "3"))
DEFAULT_LLM_PROVIDER = "vertex_ai"
DEFAULT_OLLAMA_BASE_URL = "http://localhost:11434"

app = FastAPI(title="CivicMind Relay Server")


class TimeoutSession(requests.Session):
  def request(self, *args: Any, **kwargs: Any) -> requests.Response:
    kwargs.setdefault("timeout", DEFAULT_AUTH_TIMEOUT_SECONDS)
    return super().request(*args, **kwargs)


def parse_allowed_origins() -> list[str]:
  raw_value = os.getenv("CLEARLENS_ALLOWED_ORIGINS", "*")
  if raw_value.strip() == "*":
    return DEFAULT_ALLOWED_ORIGINS
  return [origin.strip() for origin in raw_value.split(",") if origin.strip()]


app.add_middleware(
  CORSMiddleware,
  allow_origins=parse_allowed_origins(),
  allow_methods=["*"],
  allow_headers=["*"],
)


class AnalyzeRequest(BaseModel):
  text: str = Field(min_length=40)
  title: str | None = None
  url: str | None = None
  language: str | None = None


class SummaryItem(BaseModel):
  stance: str = ""
  objectivity: str = ""
  summary: str = ""


class ParallelReportingItem(BaseModel):
  stance: str
  simulated_headline: str
  core_summary: str


class AnalyzeResponse(BaseModel):
  summary: SummaryItem = Field(default_factory=SummaryItem)
  missing_context: list[str] = Field(default_factory=list)
  parallel_reporting: list[ParallelReportingItem] = Field(default_factory=list)
  meta: dict[str, Any] = Field(default_factory=dict)


class InvalidModelOutputError(Exception):
  pass


@app.get("/health")
def healthcheck() -> dict[str, Any]:
  provider = resolve_llm_provider()
  return {
    "status": "ok",
    "llm_provider": provider,
    "vertex_location": os.getenv("VERTEX_AI_LOCATION", DEFAULT_LOCATION),
    "vertex_endpoint": os.getenv("VERTEX_AI_ENDPOINT", ""),
    "vertex_prediction_host": normalize_prediction_host(os.getenv("VERTEX_AI_PREDICTION_HOST", "")),
    "ollama_base_url": normalize_ollama_base_url(os.getenv("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL)),
    "ollama_model": os.getenv("OLLAMA_MODEL", "").strip(),
    "project_id": resolve_project_id(None),
  }


@app.post("/api/analyze", response_model=AnalyzeResponse)
async def analyze_text(request: AnalyzeRequest) -> AnalyzeResponse:
  provider = resolve_llm_provider()
  requester, provider_meta = await build_model_requester(provider)
  analysis, attempt_count = await generate_analysis_with_retries(
    request=request,
    requester=requester,
  )
  analysis["meta"] = {
    "llm_provider": provider,
    "attempt_count": attempt_count,
    **provider_meta,
  }
  return AnalyzeResponse(**analysis)


def build_analysis_instruction(request: AnalyzeRequest) -> str:
  clean_text = sanitize_text(request.text)[:DEFAULT_MAX_INPUT_CHARS]
  title = sanitize_text(request.title or "Untitled article")
  url = sanitize_text(request.url or "Unknown URL")
  language = sanitize_text(request.language or "unknown")
  return f"""
You are CivicMind, a bridge-building analysis assistant focused only on extreme partisan conflict in U.S. mainstream media.

Task:
Analyze the article below and return exactly one valid JSON object.
Your job is to identify and explain extreme Democratic-aligned versus Republican-aligned viewpoints in U.S. mainstream media.
Only analyze partisan conflict involving the two major U.S. political camps: Democrats and Republicans.
The goal is to help supporters of each side better understand how the opposing side frames the issue, so users can reflect more calmly and reduce polarization.
Do not decide whether either side is right or wrong.
Do not take a political side.
Do not output markdown.
Do not explain your reasoning.
Do not continue or rewrite the article.
Start with {{ and end with }}.
Return compact JSON on a single line.

Required JSON schema:
{{
  "summary": {{
    "stance": "string",
    "objectivity": "string",
    "summary": "string"
  }},
  "missing_context": ["string"],
  "parallel_reporting": [
    {{
      "stance": "string",
      "simulated_headline": "string",
      "core_summary": "string"
    }}
  ]
}}

Rules:
- Stay strictly within U.S. partisan conflict between Democratic-aligned and Republican-aligned viewpoints.
- Focus only on clearly extreme or strongly polarized left-vs-right framing in mainstream U.S. political media.
- Relevant patterns include emotional escalation, dehumanizing language, absolute certainty, conspiracy framing, scapegoating, and hostile in-group versus out-group narratives directed across party lines.
- If the article is not mainly about U.S. Democratic-versus-Republican conflict, say so briefly in summary and return empty arrays when appropriate.
- For summary.stance, classify the dominant framing as one of: "Extreme Democratic-aligned framing", "Extreme Republican-aligned framing", "Mixed or competing partisan framing", "Unclear", or "Outside scope".
- For summary.objectivity, assess partisan intensity and polarization risk in concise language such as "Strong Democratic-aligned framing; high polarization risk" or "Strong Republican-aligned framing; high polarization risk".
- For summary.summary, write a short neutral synopsis of the article in one or two short sentences.
- For missing_context, mention omitted facts, missing voices, assumptions, or overlooked concerns that a supporter of the opposing U.S. party would need in order to understand the issue more fairly.
- For parallel_reporting, provide alternative mainstream framings from the opposing U.S. party perspective that could help Democrats and Republicans better understand each other without endorsing falsehoods, hostility, or extremism.
- Base every judgment on the provided text.
- Do not invent motives or hidden intent unless the wording strongly supports that inference.
- Do not label the article good, bad, true, false, safe, or unsafe.
- Use calm, respectful language that encourages understanding across party lines rather than outrage.
- Keep each list between 0 and 3 items.
- If there is not enough information, return empty arrays.
- Keep every string concise.
- If the stance is unclear, say "Unclear".
- Each core_summary must be one short sentence.
- Do not quote long passages from the article.
- Do not repeat the article text.

Article metadata:
Title: {title}
URL: {url}
Language hint: {language}

Article text:
{clean_text}
""".strip()


def build_repair_instruction(raw_output: str) -> str:
  trimmed_output = sanitize_text(raw_output)[:3000]
  return f"""
Convert the following draft into exactly one valid JSON object.
Do not add commentary.
Do not use markdown fences.
If a field is missing or unusable, keep the required schema and use empty arrays or empty strings as needed.
Preserve the original U.S. Democratic-versus-Republican bridge-building framing when possible.
Return compact JSON on a single line.

Required JSON schema:
{{
  "summary": {{
    "stance": "string",
    "objectivity": "string",
    "summary": "string"
  }},
  "missing_context": ["string"],
  "parallel_reporting": [
    {{
      "stance": "string",
      "simulated_headline": "string",
      "core_summary": "string"
    }}
  ]
}}

Draft output:
{trimmed_output}
""".strip()


def wrap_vertex_prompt(instruction_text: str) -> str:
  return (
    "<start_of_turn>user\n"
    f"{instruction_text}<end_of_turn>\n"
    "<start_of_turn>model\n"
  )


def build_vertex_prediction_instance(prompt: str, *, max_tokens: int = 768) -> dict[str, Any]:
  return {
    "prompt": prompt,
    "max_tokens": max_tokens,
    "temperature": 0.1,
    "top_p": 0.95,
    "top_k": 20,
    "raw_response": True,
    "stop": ["<end_of_turn>", "<start_of_turn>user", "<start_of_turn>model"],
  }


def build_ollama_system_prompt() -> str:
  return (
    "You are CivicMind, a bridge-building assistant focused only on extreme partisan conflict in U.S. mainstream media. "
    "Analyze only Democratic-aligned versus Republican-aligned viewpoints, especially strongly polarized or extreme framing. "
    "Help users understand how the opposing party perspective is framed so Democrats and Republicans can better understand each other. "
    "Look for emotional escalation, dehumanizing language, absolute certainty, conspiracy framing, scapegoating, and hostile us-versus-them narratives across party lines. "
    "Stay calm, respectful, and nonpartisan. Do not label content as right or wrong. Return only valid JSON matching the requested schema."
  )


def build_analysis_schema() -> dict[str, Any]:
  return {
    "type": "object",
    "properties": {
      "summary": {
        "type": "object",
        "properties": {
          "stance": {"type": "string"},
          "objectivity": {"type": "string"},
          "summary": {"type": "string"},
        },
        "required": ["stance", "objectivity", "summary"],
        "additionalProperties": False,
      },
      "missing_context": {
        "type": "array",
        "items": {"type": "string"},
      },
      "parallel_reporting": {
        "type": "array",
        "items": {
          "type": "object",
          "properties": {
            "stance": {"type": "string"},
            "simulated_headline": {"type": "string"},
            "core_summary": {"type": "string"},
          },
          "required": ["stance", "simulated_headline", "core_summary"],
          "additionalProperties": False,
        },
      },
    },
    "required": ["summary", "missing_context", "parallel_reporting"],
    "additionalProperties": False,
  }


async def build_model_requester(
  provider: str,
) -> tuple[Callable[[str, int], Awaitable[str]], dict[str, Any]]:
  if provider == "vertex_ai":
    return await build_vertex_requester()

  if provider == "ollama":
    return build_ollama_requester()

  raise HTTPException(
    status_code=500,
    detail=f"Unsupported LLM_PROVIDER '{provider}'. Use 'vertex_ai' or 'ollama'.",
  )


async def build_vertex_requester() -> tuple[Callable[[str, int], Awaitable[str]], dict[str, Any]]:
  access_token, project_id = await asyncio.to_thread(get_vertex_access_token)
  vertex_endpoint = build_vertex_endpoint_resource(project_id)

  async def requester(instruction_text: str, max_tokens: int) -> str:
    return await request_vertex_model_output(
      endpoint_resource=vertex_endpoint,
      access_token=access_token,
      project_id=project_id,
      prompt=wrap_vertex_prompt(instruction_text),
      max_tokens=max_tokens,
    )

  return requester, {
    "project_id": project_id,
    "vertex_endpoint": vertex_endpoint,
    "location": extract_location_from_endpoint(vertex_endpoint),
    "vertex_prediction_host": normalize_prediction_host(os.getenv("VERTEX_AI_PREDICTION_HOST", "")),
  }


def build_ollama_requester() -> tuple[Callable[[str, int], Awaitable[str]], dict[str, Any]]:
  ollama_base_url = normalize_ollama_base_url(os.getenv("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL))
  ollama_model = os.getenv("OLLAMA_MODEL", "").strip()

  if not ollama_model:
    raise HTTPException(
      status_code=500,
      detail="OLLAMA_MODEL is not configured. Set it to a local Ollama model name before using LLM_PROVIDER=ollama.",
    )

  async def requester(instruction_text: str, max_tokens: int) -> str:
    return await request_ollama_model_output(
      ollama_base_url=ollama_base_url,
      ollama_model=ollama_model,
      instruction_text=instruction_text,
      max_tokens=max_tokens,
    )

  return requester, {
    "ollama_base_url": ollama_base_url,
    "ollama_model": ollama_model,
  }


async def generate_analysis_with_retries(
  *,
  request: AnalyzeRequest,
  requester: Callable[[str, int], Awaitable[str]],
) -> tuple[dict[str, Any], int]:
  prompts = [
    build_analysis_instruction(request),
  ]
  last_error = "The model did not return valid JSON."
  last_raw_output = ""

  for attempt in range(1, DEFAULT_MAX_ANALYSIS_ATTEMPTS + 1):
    prompt = prompts[-1]
    max_tokens = 768 if attempt == 1 else 512
    raw_text = await requester(prompt, max_tokens)
    last_raw_output = raw_text

    try:
      return parse_analysis_text(raw_text), attempt
    except InvalidModelOutputError as error:
      last_error = str(error)
      if attempt == 1:
        prompts.append(build_repair_instruction(raw_text))
      elif attempt < DEFAULT_MAX_ANALYSIS_ATTEMPTS:
        prompts.append(build_analysis_instruction(request))

  raise HTTPException(
    status_code=502,
    detail=f"{last_error} Raw output preview: {last_raw_output[:400]}",
  )


async def request_vertex_model_output(
  *,
  endpoint_resource: str,
  access_token: str,
  project_id: str,
  prompt: str,
  max_tokens: int,
) -> str:
  vertex_response = await call_vertex_endpoint(
    endpoint_resource=endpoint_resource,
    access_token=access_token,
    project_id=project_id,
    prompt=prompt,
    max_tokens=max_tokens,
  )
  predictions = vertex_response.get("predictions", [])
  if not predictions:
    raise HTTPException(status_code=502, detail="Vertex AI did not return any predictions.")

  raw_prediction = predictions[0]
  raw_text = extract_prediction_text(raw_prediction)
  if not raw_text:
    raise HTTPException(status_code=502, detail="Vertex AI returned an empty response.")

  return raw_text


async def request_ollama_model_output(
  *,
  ollama_base_url: str,
  ollama_model: str,
  instruction_text: str,
  max_tokens: int,
) -> str:
  request_url = build_ollama_generate_url(ollama_base_url)
  payload = {
    "model": ollama_model,
    "system": build_ollama_system_prompt(),
    "prompt": instruction_text,
    "format": build_analysis_schema(),
    "stream": False,
    "options": {
      "temperature": 0.1,
      "top_p": 0.95,
      "top_k": 20,
      "num_predict": max_tokens,
    },
  }

  async with httpx.AsyncClient(timeout=60.0) as client:
    try:
      response = await client.post(request_url, json=payload)
      response.raise_for_status()
    except httpx.HTTPStatusError as error:
      detail = error.response.text
      raise HTTPException(
        status_code=502,
        detail=f"Ollama request failed: HTTP {error.response.status_code} - {detail}",
      ) from error
    except httpx.HTTPError as error:
      raise HTTPException(status_code=502, detail=f"Ollama network error: {error}") from error

  try:
    response_body = response.json()
  except ValueError as error:
    raise HTTPException(
      status_code=502,
      detail=f"Ollama returned a non-JSON response: {response.text[:400]}",
    ) from error

  raw_text = extract_ollama_text(response_body)
  if not raw_text:
    raise HTTPException(status_code=502, detail="Ollama returned an empty response.")

  return raw_text


def parse_analysis_text(raw_text: str) -> dict[str, Any]:
  payload = parse_json_response(raw_text)
  return normalize_analysis_payload(payload)


async def call_vertex_endpoint(
  *,
  endpoint_resource: str,
  access_token: str,
  project_id: str,
  prompt: str,
  max_tokens: int,
) -> dict[str, Any]:
  request_url = build_predict_url(endpoint_resource)
  payload = {
    "instances": [
      build_vertex_prediction_instance(prompt, max_tokens=max_tokens)
    ]
  }

  headers = {
    "Authorization": f"Bearer {access_token}",
    "Content-Type": "application/json",
    "x-goog-user-project": project_id,
  }

  async with httpx.AsyncClient(timeout=60.0) as client:
    try:
      response = await client.post(request_url, headers=headers, json=payload)
      response.raise_for_status()
      return response.json()
    except httpx.HTTPStatusError as error:
      detail = error.response.text
      dedicated_dns = extract_dedicated_dns_hint(detail)
      if dedicated_dns:
        detail = (
          f"{detail} Set VERTEX_AI_PREDICTION_HOST={dedicated_dns} "
          "and restart the backend so requests use the dedicated Vertex AI domain."
        )
      raise HTTPException(
        status_code=502,
        detail=f"Vertex AI request failed: HTTP {error.response.status_code} - {detail}",
      ) from error
    except httpx.HTTPError as error:
      raise HTTPException(status_code=502, detail=f"Vertex AI network error: {error}") from error


def extract_prediction_text(prediction: Any) -> str:
  if isinstance(prediction, str):
    return prediction

  if isinstance(prediction, dict):
    for key in ("content", "generated_text", "output", "text"):
      value = prediction.get(key)
      if isinstance(value, str):
        return value

  if isinstance(prediction, list):
    return "\n".join(part for part in prediction if isinstance(part, str))

  return ""


def extract_ollama_text(response_body: dict[str, Any]) -> str:
  response_text = response_body.get("response")
  if isinstance(response_text, str):
    return response_text

  message = response_body.get("message")
  if isinstance(message, dict):
    content = message.get("content")
    if isinstance(content, str):
      return content

  return ""


def parse_json_response(raw_text: str) -> Any:
  cleaned = raw_text.strip()
  cleaned = cleaned.replace("<start_of_turn>model", "").replace("<end_of_turn>", "").strip()
  cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
  cleaned = re.sub(r"\s*```$", "", cleaned)

  try:
    return json.loads(cleaned)
  except json.JSONDecodeError:
    extracted = extract_balanced_json_object(cleaned)
    if not extracted:
      raise InvalidModelOutputError(f"The model did not return valid JSON: {raw_text[:400]}")

    try:
      return json.loads(extracted)
    except json.JSONDecodeError as error:
      raise InvalidModelOutputError(f"The model response could not be parsed as JSON: {cleaned[:400]}") from error


def extract_balanced_json_object(text: str) -> str:
  start = text.find("{")
  if start == -1:
    return ""

  depth = 0
  in_string = False
  escaped = False

  for index in range(start, len(text)):
    char = text[index]

    if in_string:
      if escaped:
        escaped = False
      elif char == "\\":
        escaped = True
      elif char == '"':
        in_string = False
      continue

    if char == '"':
      in_string = True
      continue

    if char == "{":
      depth += 1
    elif char == "}":
      depth -= 1
      if depth == 0:
        return text[start:index + 1]

  return ""


def normalize_analysis_payload(payload: Any) -> dict[str, Any]:
  if not isinstance(payload, dict):
    return {
      "summary": SummaryItem().model_dump(),
      "missing_context": [],
      "parallel_reporting": [],
    }

  summary_payload = payload.get("summary")
  summary = SummaryItem().model_dump()
  if isinstance(summary_payload, dict):
    stance = sanitize_text(summary_payload.get("stance"))
    objectivity = sanitize_text(summary_payload.get("objectivity"))
    summary_text = sanitize_text(summary_payload.get("summary"))
    if stance or objectivity or summary_text:
      summary = {
        "stance": stance,
        "objectivity": objectivity,
        "summary": summary_text,
      }

  missing_context = [
    sanitize_text(item)
    for item in ensure_list(payload.get("missing_context"))[:4]
    if sanitize_text(item)
  ]

  parallel_reporting = []
  for item in ensure_list(payload.get("parallel_reporting"))[:4]:
    if not isinstance(item, dict):
      continue
    stance = sanitize_text(item.get("stance"))
    simulated_headline = sanitize_text(item.get("simulated_headline"))
    core_summary = sanitize_text(item.get("core_summary"))
    if stance and simulated_headline and core_summary:
      parallel_reporting.append(
        {
          "stance": stance,
          "simulated_headline": simulated_headline,
          "core_summary": core_summary,
        }
      )

  return {
    "summary": summary,
    "missing_context": missing_context,
    "parallel_reporting": parallel_reporting,
  }


def get_vertex_access_token() -> tuple[str, str]:
  try:
    project_hint = resolve_project_id(None)
    credentials, discovered_project = load_google_credentials()
    project_id = resolve_project_id(discovered_project)
    if hasattr(credentials, "with_quota_project") and project_id:
      credentials = credentials.with_quota_project(project_id)
    credentials.refresh(GoogleAuthRequest(session=TimeoutSession()))
  except DefaultCredentialsError as error:
    raise HTTPException(
      status_code=500,
      detail=(
        "Google Cloud credentials were not found. Set GOOGLE_APPLICATION_CREDENTIALS "
        "or run gcloud auth application-default login first."
      ),
    ) from error
  except Exception as error:
    raise HTTPException(status_code=500, detail=f"Google Cloud authentication failed: {error}") from error

  token = getattr(credentials, "token", None)
  if not token:
    raise HTTPException(status_code=500, detail="Google Cloud access token is empty.")

  if not project_id and project_hint:
    project_id = project_hint

  if not project_id:
    raise HTTPException(
      status_code=500,
      detail="Google Cloud project ID could not be resolved. Set GOOGLE_CLOUD_PROJECT.",
    )

  return token, project_id


def build_vertex_endpoint_resource(project_id: str) -> str:
  raw_endpoint = os.getenv("VERTEX_AI_ENDPOINT", "").strip()
  if not raw_endpoint:
    raise HTTPException(
      status_code=500,
      detail=(
        "VERTEX_AI_ENDPOINT is not configured. Provide the full resource name, for example "
        "projects/PROJECT_ID/locations/us-central1/endpoints/ENDPOINT_ID"
      ),
    )

  if raw_endpoint.startswith("projects/"):
    return raw_endpoint

  location = os.getenv("VERTEX_AI_LOCATION", DEFAULT_LOCATION)
  return f"projects/{project_id}/locations/{location}/endpoints/{raw_endpoint}"


def build_predict_url(endpoint_resource: str) -> str:
  prediction_host = normalize_prediction_host(os.getenv("VERTEX_AI_PREDICTION_HOST", ""))
  if prediction_host:
    return f"https://{prediction_host}/v1/{endpoint_resource}:predict"

  location = extract_location_from_endpoint(endpoint_resource)
  return f"https://{location}-aiplatform.googleapis.com/v1/{endpoint_resource}:predict"


def build_ollama_generate_url(base_url: str) -> str:
  return f"{base_url}/api/generate"


def resolve_llm_provider() -> str:
  provider = os.getenv("LLM_PROVIDER", DEFAULT_LLM_PROVIDER).strip().lower()
  if provider not in {"vertex_ai", "ollama"}:
    raise HTTPException(
      status_code=500,
      detail=f"Unsupported LLM_PROVIDER '{provider}'. Use 'vertex_ai' or 'ollama'.",
    )
  return provider


def resolve_project_id(discovered_project: str | None) -> str:
  return (
    os.getenv("GOOGLE_CLOUD_PROJECT")
    or os.getenv("VERTEX_AI_PROJECT")
    or discovered_project
    or ""
  ).strip()


def load_google_credentials() -> tuple[Any, str | None]:
  service_account_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "").strip()
  if service_account_path:
    return google.auth.load_credentials_from_file(service_account_path, scopes=VERTEX_SCOPES)

  adc_path = Path.home() / ".config" / "gcloud" / "application_default_credentials.json"
  if adc_path.exists():
    return google.auth.load_credentials_from_file(str(adc_path), scopes=VERTEX_SCOPES)

  if is_google_runtime():
    return google.auth.default(scopes=VERTEX_SCOPES)

  raise DefaultCredentialsError("No local ADC file or service account credentials were found.")


def is_google_runtime() -> bool:
  runtime_markers = (
    "K_SERVICE",
    "K_REVISION",
    "GAE_ENV",
    "FUNCTION_TARGET",
    "FUNCTION_NAME",
  )
  return any(os.getenv(marker) for marker in runtime_markers)


def normalize_prediction_host(value: str) -> str:
  host = (value or "").strip()
  host = re.sub(r"^https?://", "", host)
  return host.rstrip("/")


def normalize_ollama_base_url(value: str) -> str:
  base_url = (value or DEFAULT_OLLAMA_BASE_URL).strip().rstrip("/")
  if base_url.endswith("/api"):
    base_url = base_url[:-4]
  return base_url


def extract_dedicated_dns_hint(detail: str) -> str:
  match = re.search(r"'([^']+\.prediction\.vertexai\.goog)'", detail or "")
  return match.group(1) if match else ""


def extract_location_from_endpoint(endpoint_resource: str) -> str:
  match = re.search(r"/locations/([^/]+)/", endpoint_resource)
  return match.group(1) if match else os.getenv("VERTEX_AI_LOCATION", DEFAULT_LOCATION)


def ensure_list(value: Any) -> list[Any]:
  return value if isinstance(value, list) else []


def sanitize_text(value: Any) -> str:
  return re.sub(r"\s+", " ", str(value or "")).strip()


if __name__ == "__main__":
  import uvicorn

  uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8000")))
