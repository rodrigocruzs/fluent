"""
Fluent backend — FastAPI app.

Endpoints:
  POST /auth/register         { email, password }  → { token }
  POST /auth/login            { email, password }  → { token }
  GET  /auth/me               → { email, created_at }
  POST /auth/change-password  { current_password, new_password }
  DELETE /auth/delete-account
  POST /coach                 { transcript, native_language, job_context }  → [issues]
  GET  /billing/status        → { plan_status, trial_ends_at, current_period_end }
  POST /billing/checkout      → { url }
  POST /billing/portal        → { url }
  POST /billing/webhook       (Stripe webhook)

Run locally:
  ANTHROPIC_API_KEY=sk-ant-... uvicorn backend.main:app --reload --port 8000
"""

import os
import time
from dotenv import load_dotenv
load_dotenv(".env.local")
from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr
import json
import stripe
from anthropic import Anthropic

from backend.database import (
    init_db, create_user, get_user_by_email, get_user_by_id,
    save_session, get_sessions, get_session_with_issues,
    update_user_password, delete_user,
    update_user_billing, get_user_by_stripe_customer,
)
from backend.auth import hash_password, verify_password, create_token, decode_token

STRIPE_SECRET_KEY      = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET  = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PRICE_ID        = os.environ.get("STRIPE_PRICE_ID", "")         # $10/mo price ID
STRIPE_TRIAL_DAYS      = 7
FRONTEND_URL           = os.environ.get("FRONTEND_URL", "https://fluent-lemon.vercel.app")

if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY

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


def _current_user(creds: HTTPAuthorizationCredentials = Depends(_bearer)) -> dict:
    user_id = decode_token(creds.credentials)
    if user_id is None:
        raise HTTPException(401, "Invalid or expired token.")
    user = get_user_by_id(user_id)
    if not user:
        raise HTTPException(401, "User not found.")
    return user


# ── Account management ────────────────────────────────────────────────────────

@app.get("/auth/me")
def get_me(user: dict = Depends(_current_user)):
    return {"email": user["email"], "created_at": user["created_at"]}


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


@app.post("/auth/change-password")
def change_password(req: ChangePasswordRequest, user: dict = Depends(_current_user)):
    if not verify_password(req.current_password, user["hashed_password"]):
        raise HTTPException(400, "Current password is incorrect.")
    if len(req.new_password) < 8:
        raise HTTPException(400, "New password must be at least 8 characters.")
    update_user_password(user["id"], hash_password(req.new_password))
    return {"ok": True}


@app.delete("/auth/delete-account")
def delete_account(user: dict = Depends(_current_user)):
    # Cancel Stripe subscription if active
    if STRIPE_SECRET_KEY and user.get("stripe_subscription_id"):
        try:
            stripe.Subscription.cancel(user["stripe_subscription_id"])
        except stripe.StripeError:
            pass
    delete_user(user["id"])
    return {"ok": True}


# ── Billing ───────────────────────────────────────────────────────────────────

@app.get("/billing/status")
def billing_status(user: dict = Depends(_current_user)):
    return {
        "plan_status":        user.get("plan_status", "trial"),
        "trial_ends_at":      user.get("trial_ends_at"),
        "current_period_end": user.get("current_period_end"),
    }


class CheckoutRequest(BaseModel):
    success_url: str | None = None
    cancel_url:  str | None = None


@app.post("/billing/checkout")
def create_checkout(req: CheckoutRequest, user: dict = Depends(_current_user)):
    if not STRIPE_SECRET_KEY or not STRIPE_PRICE_ID:
        raise HTTPException(503, "Billing not configured.")

    success_url = req.success_url or f"{FRONTEND_URL}/api/billing/checkout-success"
    cancel_url  = req.cancel_url  or f"{FRONTEND_URL}?checkout=cancel"

    # Create or reuse Stripe customer
    customer_id = user.get("stripe_customer_id")
    if not customer_id:
        customer = stripe.Customer.create(email=user["email"])
        customer_id = customer.id
        update_user_billing(user["id"], stripe_customer_id=customer_id)

    # Calculate remaining trial days from account creation, minimum 0
    trial_ends_at = user.get("trial_ends_at")
    if trial_ends_at:
        remaining_days = max(0, int((trial_ends_at - time.time()) / 86400))
    else:
        remaining_days = 0

    sub_data = {"trial_period_days": remaining_days} if remaining_days > 0 else {}

    session = stripe.checkout.Session.create(
        customer=customer_id,
        payment_method_types=["card"],
        line_items=[{"price": STRIPE_PRICE_ID, "quantity": 1}],
        mode="subscription",
        subscription_data=sub_data,
        success_url=success_url,
        cancel_url=cancel_url,
    )
    return {"url": session.url}


@app.get("/billing/checkout-success")
def checkout_success():
    from fastapi.responses import HTMLResponse
    return HTMLResponse("""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<title>Fluent — Subscribed</title>
<style>
  body { font-family: -apple-system, sans-serif; background: #fff; display: flex;
         align-items: center; justify-content: center; min-height: 100vh; margin: 0; }
  .card { text-align: center; max-width: 360px; padding: 48px 32px; }
  .logo { width: 48px; height: 48px; border-radius: 14px; background: #C96442;
          display: inline-flex; align-items: center; justify-content: center; margin-bottom: 24px; }
  h1 { font-size: 22px; font-weight: 600; letter-spacing: -0.02em; margin: 0 0 8px; color: #1a1a1a; }
  p  { font-size: 14px; color: #8a8a8a; margin: 0 0 24px; line-height: 1.5; }
  .close { font-size: 13px; color: #b5b5b5; }
</style>
</head>
<body>
<div class="card">
  <div class="logo">
    <svg width="24" height="24" viewBox="0 0 14 14" fill="none">
      <path d="M2 4 Q 4 1, 7 4 T 12 4" stroke="#fff" stroke-width="1.6" stroke-linecap="round" fill="none"/>
      <path d="M2 7 Q 4 4, 7 7 T 12 7" stroke="#fff" stroke-width="1.6" stroke-linecap="round" fill="none" opacity="0.7"/>
      <path d="M2 10 Q 4 7, 7 10 T 12 10" stroke="#fff" stroke-width="1.6" stroke-linecap="round" fill="none" opacity="0.4"/>
    </svg>
  </div>
  <h1>You're all set.</h1>
  <p>Your Fluent subscription is active. You can close this tab and go back to the app.</p>
  <p class="close">This tab will close automatically.</p>
</div>
<script>setTimeout(() => window.close(), 2000);</script>
</body>
</html>""")


@app.post("/billing/portal")
def billing_portal(user: dict = Depends(_current_user)):
    if not STRIPE_SECRET_KEY:
        raise HTTPException(503, "Billing not configured.")

    customer_id = user.get("stripe_customer_id")
    if not customer_id:
        raise HTTPException(400, "No billing account found.")

    session = stripe.billing_portal.Session.create(
        customer=customer_id,
        return_url=f"{FRONTEND_URL}",
    )
    return {"url": session.url}


@app.post("/billing/webhook")
async def stripe_webhook(request: Request):
    if not STRIPE_WEBHOOK_SECRET:
        raise HTTPException(503, "Webhook not configured.")

    payload = await request.body()
    sig = request.headers.get("stripe-signature", "")
    try:
        event = stripe.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK_SECRET)
    except stripe.SignatureVerificationError:
        raise HTTPException(400, "Invalid webhook signature.")

    obj = event["data"]["object"]

    if event["type"] == "checkout.session.completed":
        customer_id = obj.get("customer")
        sub_id      = obj.get("subscription")
        user = get_user_by_stripe_customer(customer_id)
        if user:
            update_user_billing(user["id"],
                stripe_subscription_id=sub_id,
                plan_status="trial",
                trial_ends_at=time.time() + STRIPE_TRIAL_DAYS * 86400,
            )

    elif event["type"] == "customer.subscription.updated":
        customer_id = obj.get("customer")
        user = get_user_by_stripe_customer(customer_id)
        if user:
            status = obj.get("status")
            plan_status = "active" if status == "active" else \
                          "trial"  if status == "trialing" else \
                          "canceled"
            update_user_billing(user["id"],
                plan_status=plan_status,
                trial_ends_at=obj.get("trial_end"),
                current_period_end=obj["current_period_end"],
            )

    elif event["type"] in ("customer.subscription.deleted", "customer.subscription.paused"):
        customer_id = obj.get("customer")
        user = get_user_by_stripe_customer(customer_id)
        if user:
            update_user_billing(user["id"],
                plan_status="canceled",
                current_period_end=obj.get("current_period_end"),
            )

    elif event["type"] == "invoice.paid":
        customer_id = obj.get("customer")
        user = get_user_by_stripe_customer(customer_id)
        if user:
            update_user_billing(user["id"], plan_status="active")

    return {"ok": True}


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


# ── Sessions ─────────────────────────────────────────────────────────────────

class SessionPayload(BaseModel):
    slug: str
    name: str
    date: str
    duration: float = 0
    transcript: str = ""
    issues: list[dict] = []


@app.post("/sessions")
def create_session(payload: SessionPayload, user_id: int = Depends(_current_user_id)):
    session_id = save_session(
        user_id=user_id,
        slug=payload.slug,
        name=payload.name,
        date=payload.date,
        duration=payload.duration,
        transcript=payload.transcript,
        issues=payload.issues,
    )
    return {"id": session_id}


@app.get("/sessions")
def list_sessions(user_id: int = Depends(_current_user_id)):
    return get_sessions(user_id)


@app.get("/sessions/{slug}")
def get_session(slug: str, user_id: int = Depends(_current_user_id)):
    session = get_session_with_issues(user_id, slug)
    if not session:
        raise HTTPException(404, "Session not found.")
    return session


# ── Health ───────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    return {"status": "ok"}
