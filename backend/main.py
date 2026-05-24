"""
Fluent backend — FastAPI app.

Endpoints:
  POST /auth/register   { email, password }  → { token }
  POST /auth/login      { email, password }  → { token }
  POST /coach           { transcript, native_language, job_context }  → [issues]

Run locally:
  ANTHROPIC_API_KEY=sk-ant-... uvicorn backend.main:app --reload --port 8000
"""

import os
from fastapi import FastAPI, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr
import json
from anthropic import Anthropic

from backend.database import init_db, create_user, get_user_by_email, get_user_by_id
from backend.auth import hash_password, verify_password, create_token, decode_token

app = FastAPI(title="Fluent API")
_bearer = HTTPBearer()

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

COACH_SYSTEM = """You are an English language coach specialising in helping non-native speakers sound more natural and professional in business meetings.

The user's native language is {native_language}.
Their job context: {job_context}.

You will receive a transcript of what they said in a meeting. Your job is to identify specific issues and suggest improvements.

For each issue found, return a JSON array with this structure:
[
  {{
    "category": "Grammar" | "Phrasing" | "Vocabulary",
    "original": "exactly what they said",
    "improved": "what a fluent native speaker would say",
    "explanation": "one sentence explaining why, specific to their native language background"
  }}
]

Rules:
- Only flag real issues. If something is correct and natural, ignore it.
- Be specific — don't give generic grammar advice.
- If the sentence is fine, return an empty array.
- Return JSON only, no preamble, no markdown."""


# ── Startup ─────────────────────────────────────────────────────────────────

@app.on_event("startup")
def startup():
    init_db()


# ── Auth ─────────────────────────────────────────────────────────────────────

class AuthRequest(BaseModel):
    email: EmailStr
    password: str


class TokenResponse(BaseModel):
    token: str


@app.post("/auth/register", response_model=TokenResponse)
def register(req: AuthRequest):
    if len(req.password) < 8:
        raise HTTPException(400, "Password must be at least 8 characters.")
    if get_user_by_email(req.email):
        raise HTTPException(409, "An account with that email already exists.")
    user_id = create_user(req.email, hash_password(req.password))
    return TokenResponse(token=create_token(user_id))


@app.post("/auth/login", response_model=TokenResponse)
def login(req: AuthRequest):
    user = get_user_by_email(req.email)
    if not user or not verify_password(req.password, user["hashed_password"]):
        raise HTTPException(401, "Incorrect email or password.")
    return TokenResponse(token=create_token(user["id"]))


# ── Auth dependency ───────────────────────────────────────────────────────────

def _current_user_id(creds: HTTPAuthorizationCredentials = Depends(_bearer)) -> int:
    user_id = decode_token(creds.credentials)
    if user_id is None:
        raise HTTPException(401, "Invalid or expired token.")
    if not get_user_by_id(user_id):
        raise HTTPException(401, "User not found.")
    return user_id


# ── Coach ────────────────────────────────────────────────────────────────────

class CoachRequest(BaseModel):
    transcript: str
    native_language: str = "Spanish"
    job_context: str = "Professional"


@app.post("/coach")
def coach(req: CoachRequest, user_id: int = Depends(_current_user_id)):
    if not ANTHROPIC_API_KEY:
        raise HTTPException(500, "Server is not configured with an Anthropic API key.")

    client = Anthropic(api_key=ANTHROPIC_API_KEY)
    system = COACH_SYSTEM.format(
        native_language=req.native_language,
        job_context=req.job_context,
    )
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=system,
        messages=[{"role": "user", "content": req.transcript}],
    )

    raw = response.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip().rstrip("`")

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(500, "Model returned malformed JSON.")


# ── Health ───────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok"}
