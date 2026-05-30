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
load_dotenv(".env.local", override=True)  # must run before any module reads os.environ
from fastapi import FastAPI, HTTPException, Depends, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr
import json
import stripe
from anthropic import Anthropic

from backend.database import (
    init_db, create_user, get_user_by_email, get_user_by_id,
    save_session, get_sessions, get_session_with_issues,
    update_user_password, update_user_email, delete_user,
    update_user_billing, get_user_by_stripe_customer,
    get_user_by_google_id, upsert_google_user,
)
from backend.auth import hash_password, verify_password, create_token, decode_token

STRIPE_SECRET_KEY      = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET  = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PRICE_ID        = os.environ.get("STRIPE_PRICE_ID", "")         # $10/mo price ID
STRIPE_TRIAL_DAYS      = 7
FRONTEND_URL           = os.environ.get("FRONTEND_URL", "https://fluent-lemon.vercel.app")

GOOGLE_CLIENT_ID     = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
GOOGLE_REDIRECT_URI  = os.environ.get("GOOGLE_REDIRECT_URI", "http://localhost:8001/auth/google/callback")

if STRIPE_SECRET_KEY:
    stripe.api_key = STRIPE_SECRET_KEY

app = FastAPI(title="Fluent API")
_bearer = HTTPBearer()

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

COACH_SYSTEM = """You are an English language coach helping non-native speakers sound more natural and professional in business meetings.

Their job context: {job_context}.

You will receive a transcript of what they said in a meeting. Your job is to identify specific issues and suggest improvements.

For each issue found, return a JSON array with this structure:
[
  {{
    "category": "Grammar" | "Phrasing" | "Vocabulary",
    "original": "exactly what they said",
    "improved": "what a fluent native speaker would say",
    "explanation": "one sentence explaining why this sounds more natural or professional"
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


# ── Google OAuth ─────────────────────────────────────────────────────────────

@app.get("/auth/google")
def google_auth():
    """Redirect the user's browser to Google's OAuth consent screen."""
    if not GOOGLE_CLIENT_ID:
        raise HTTPException(503, "Google sign-in is not configured.")
    import urllib.parse
    params = urllib.parse.urlencode({
        "client_id":     GOOGLE_CLIENT_ID,
        "redirect_uri":  GOOGLE_REDIRECT_URI,
        "response_type": "code",
        "scope":         "openid email profile https://www.googleapis.com/auth/calendar.readonly",
        "access_type":   "offline",
        "prompt":        "consent select_account",
    })
    from fastapi.responses import RedirectResponse
    return RedirectResponse(f"https://accounts.google.com/o/oauth2/v2/auth?{params}")


@app.get("/auth/google/callback")
def google_callback(code: str = "", error: str = ""):
    """Exchange the auth code for user info, create/update user, redirect to app."""
    import urllib.parse
    import requests as _requests
    from fastapi.responses import HTMLResponse

    def _redirect_html(url: str) -> HTMLResponse:
        return HTMLResponse(f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><title>Signing in to Fluent…</title>
<style>body{{font-family:-apple-system,sans-serif;display:flex;align-items:center;
justify-content:center;min-height:100vh;margin:0;background:#fff;color:#1a1a1a}}</style>
</head>
<body><p>Signing in to Fluent…</p>
<script>
  window.location.href = {json.dumps(url)};
  setTimeout(() => window.close(), 500);
</script>
</body></html>""")

    if error or not code:
        return _redirect_html(f"fluent://auth?error={urllib.parse.quote(error or 'access_denied')}")

    # Exchange code for tokens
    token_resp = _requests.post("https://oauth2.googleapis.com/token", data={
        "code":          code,
        "client_id":     GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "redirect_uri":  GOOGLE_REDIRECT_URI,
        "grant_type":    "authorization_code",
    }, timeout=10)
    if not token_resp.ok:
        return _redirect_html("fluent://auth?error=token_exchange_failed")

    access_token = token_resp.json().get("access_token", "")

    # Get user info from Google
    userinfo_resp = _requests.get(
        "https://www.googleapis.com/oauth2/v3/userinfo",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10,
    )
    if not userinfo_resp.ok:
        return _redirect_html("fluent://auth?error=userinfo_failed")

    info          = userinfo_resp.json()
    google_id     = info.get("sub", "")
    email         = info.get("email", "").lower().strip()
    name          = info.get("name", "") or info.get("given_name", "")
    token_data    = token_resp.json()
    refresh_token = token_data.get("refresh_token", "")
    expires_in    = token_data.get("expires_in", 3600)
    token_expiry  = time.time() + expires_in

    if not google_id or not email:
        return _redirect_html("fluent://auth?error=missing_profile")

    user_id = upsert_google_user(google_id, email, name,
                                 access_token=access_token,
                                 refresh_token=refresh_token,
                                 token_expiry=token_expiry)
    jwt     = create_token(user_id)

    # Write token to a file the app polls, and also try the engine's /signin endpoint
    import pathlib
    pending = pathlib.Path.home() / ".fluent" / "pending_auth.json"
    pending.write_text(json.dumps({"token": jwt, "name": name, "email": email}))
    try:
        _requests.post("http://127.0.0.1:2788/signin", json={"token": jwt}, timeout=2)
    except Exception:
        pass

    return _redirect_html(f"fluent://auth?token={urllib.parse.quote(jwt)}&name={urllib.parse.quote(name)}&email={urllib.parse.quote(email)}")


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


# ── Calendar ─────────────────────────────────────────────────────────────────

def _refresh_google_token(user: dict) -> str | None:
    import requests as _requests
    access_token  = user.get("google_access_token", "")
    refresh_token = user.get("google_refresh_token", "")
    expiry        = user.get("google_token_expiry") or 0

    if access_token and time.time() < expiry - 60:
        return access_token
    if not refresh_token:
        return None

    resp = _requests.post("https://oauth2.googleapis.com/token", data={
        "client_id":     GOOGLE_CLIENT_ID,
        "client_secret": GOOGLE_CLIENT_SECRET,
        "refresh_token": refresh_token,
        "grant_type":    "refresh_token",
    }, timeout=10)
    if not resp.ok:
        return None

    data       = resp.json()
    new_token  = data.get("access_token", "")
    new_expiry = time.time() + data.get("expires_in", 3600)
    update_user_billing(user["id"],
        **{"google_access_token": new_token, "google_token_expiry": new_expiry})
    return new_token


@app.get("/calendar/upcoming")
def calendar_upcoming(user: dict = Depends(_current_user)):
    import requests as _requests
    from datetime import datetime, timezone

    token = _refresh_google_token(user)
    if not token:
        raise HTTPException(403, "Google Calendar not connected. Please sign in with Google.")

    now_iso = datetime.now(timezone.utc).isoformat()
    resp = _requests.get(
        "https://www.googleapis.com/calendar/v3/calendars/primary/events",
        headers={"Authorization": f"Bearer {token}"},
        params={
            "timeMin":      now_iso,
            "maxResults":   3,
            "singleEvents": True,
            "orderBy":      "startTime",
            "fields":       "items(id,summary,start,end,attendees)",
        },
        timeout=10,
    )
    if not resp.ok:
        raise HTTPException(502, "Failed to fetch calendar events.")

    events = []
    for item in resp.json().get("items", []):
        start = item.get("start", {})
        end   = item.get("end",   {})
        events.append({
            "id":        item.get("id", ""),
            "title":     item.get("summary", "Untitled"),
            "start":     start.get("dateTime") or start.get("date", ""),
            "end":       end.get("dateTime")   or end.get("date", ""),
            "attendees": len(item.get("attendees") or []),
        })
    return events


# ── Account management ────────────────────────────────────────────────────────

@app.get("/auth/me")
def get_me(user: dict = Depends(_current_user)):
    return {"email": user["email"], "created_at": user["created_at"]}


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class ChangeEmailRequest(BaseModel):
    new_email: EmailStr
    password: str


@app.post("/auth/change-email")
def change_email(req: ChangeEmailRequest, user: dict = Depends(_current_user)):
    if not verify_password(req.password, user["hashed_password"]):
        raise HTTPException(400, "Password is incorrect.")
    if get_user_by_email(req.new_email):
        raise HTTPException(409, "That email is already in use.")
    update_user_email(user["id"], req.new_email)
    if STRIPE_SECRET_KEY and user.get("stripe_customer_id"):
        try:
            stripe.Customer.modify(user["stripe_customer_id"], email=req.new_email)
        except stripe.StripeError:
            pass
    return {"ok": True}


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
        "plan_status":          user.get("plan_status", "trial"),
        "trial_ends_at":        user.get("trial_ends_at"),
        "current_period_end":   user.get("current_period_end"),
        "cancel_at_period_end": user.get("cancel_at_period_end", False),
    }


@app.post("/billing/sync")
def billing_sync(user: dict = Depends(_current_user)):
    """Pull live subscription state from Stripe and update the DB."""
    import requests as _requests
    if not STRIPE_SECRET_KEY:
        raise HTTPException(503, "Billing not configured.")
    customer_id = user.get("stripe_customer_id")
    if not customer_id:
        raise HTTPException(400, "No billing account found.")
    r = _requests.get(
        "https://api.stripe.com/v1/subscriptions",
        params={"customer": customer_id, "limit": 1, "status": "all"},
        auth=(STRIPE_SECRET_KEY, ""),
        timeout=10,
    )
    data = r.json()
    subs = data.get("data", [])
    if not subs:
        return {"plan_status": user.get("plan_status", "trial")}
    sub = subs[0]
    status = sub.get("status")
    # current_period_end moved to items in newer Stripe API versions
    current_period_end = (sub.get("current_period_end") or
                          (sub.get("items", {}).get("data") or [{}])[0].get("current_period_end"))
    # Cancelled via portal sets cancel_at (scheduled) rather than cancel_at_period_end
    is_canceling = bool(sub.get("cancel_at_period_end") or sub.get("cancel_at"))
    plan_status = "active" if status == "active" else \
                  "trial"  if status == "trialing" else \
                  "canceled"
    update_user_billing(user["id"],
        stripe_subscription_id=sub.get("id"),
        plan_status=plan_status,
        trial_ends_at=sub.get("trial_end"),
        current_period_end=current_period_end,
        cancel_at_period_end=is_canceling,
    )
    return {
        "plan_status":          plan_status,
        "trial_ends_at":        sub.get("trial_end"),
        "current_period_end":   current_period_end,
        "cancel_at_period_end": is_canceling,
    }


@app.get("/billing/invoices")
def billing_invoices(user: dict = Depends(_current_user)):
    """Return the customer's default payment method + last 12 paid invoices."""
    import requests as _requests
    if not STRIPE_SECRET_KEY:
        raise HTTPException(503, "Billing not configured.")
    customer_id = user.get("stripe_customer_id")
    if not customer_id:
        raise HTTPException(400, "No billing account found.")

    auth = (STRIPE_SECRET_KEY, "")

    # Fetch customer with expanded payment method
    cust_r = _requests.get(
        f"https://api.stripe.com/v1/customers/{customer_id}",
        params={"expand[]": "invoice_settings.default_payment_method"},
        auth=auth, timeout=10,
    )
    cust = cust_r.json()

    def _card_from_obj(obj):
        if not obj or not isinstance(obj, dict): return None
        cd = obj.get("card") or {}
        if not cd.get("last4"): return None
        return {"brand": cd.get("brand", ""), "last4": cd.get("last4", ""),
                "exp_month": cd.get("exp_month"), "exp_year": cd.get("exp_year")}

    card = _card_from_obj((cust.get("invoice_settings") or {}).get("default_payment_method"))
    if not card:
        src = cust.get("default_source")
        if isinstance(src, dict) and src.get("object") == "card":
            card = _card_from_obj(src)
    if not card:
        pm_r = _requests.get(
            "https://api.stripe.com/v1/payment_methods",
            params={"customer": customer_id, "type": "card", "limit": 1},
            auth=auth, timeout=10,
        )
        pms = pm_r.json().get("data", [])
        if pms:
            card = _card_from_obj(pms[0])

    # Fetch paid invoices
    inv_r = _requests.get(
        "https://api.stripe.com/v1/invoices",
        params={"customer": customer_id, "limit": 12, "status": "paid"},
        auth=auth, timeout=10,
    )
    invoices = [
        {
            "id": inv.get("id"),
            "date": inv.get("created"),
            "amount": inv.get("amount_paid", 0),
            "currency": inv.get("currency", "usd"),
            "pdf": inv.get("invoice_pdf"),
        }
        for inv in inv_r.json().get("data", [])
    ]

    return {"card": card, "invoices": invoices}


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

    # If the customer already has a trialing subscription, cancel it so
    # the new checkout starts an immediate paid plan (no trial carry-over).
    existing_sub_id = user.get("stripe_subscription_id")
    if existing_sub_id:
        try:
            import requests as _requests
            r = _requests.get(f"https://api.stripe.com/v1/subscriptions/{existing_sub_id}",
                              auth=(STRIPE_SECRET_KEY, ""), timeout=10)
            existing = r.json()
            if existing.get("status") == "trialing":
                stripe.Subscription.cancel(existing_sub_id)
                update_user_billing(user["id"], stripe_subscription_id=None)
        except stripe.StripeError:
            pass

    session = stripe.checkout.Session.create(
        customer=customer_id,
        payment_method_types=["card"],
        line_items=[{"price": STRIPE_PRICE_ID, "quantity": 1}],
        mode="subscription",
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
        stripe.Webhook.construct_event(payload, sig, STRIPE_WEBHOOK_SECRET)
    except stripe.SignatureVerificationError:
        raise HTTPException(400, "Invalid webhook signature.")

    event = json.loads(payload)
    obj = event["data"]["object"]

    if event["type"] == "checkout.session.completed":
        customer_id    = obj.get("customer")
        sub_id         = obj.get("subscription")
        customer_email = (obj.get("customer_details") or {}).get("email") or obj.get("customer_email")
        user = get_user_by_stripe_customer(customer_id)
        if not user and customer_email:
            user = get_user_by_email(customer_email)
        if user:
            trial_ends_at = user.get("trial_ends_at") or time.time() + STRIPE_TRIAL_DAYS * 86400
            update_user_billing(user["id"],
                stripe_customer_id=customer_id,
                stripe_subscription_id=sub_id,
                plan_status="trial",
                trial_ends_at=trial_ends_at,
            )

    elif event["type"] == "customer.subscription.updated":
        customer_id = obj.get("customer")
        user = get_user_by_stripe_customer(customer_id)
        if user:
            status = obj.get("status")
            plan_status = "active" if status == "active" else \
                          "trial"  if status == "trialing" else \
                          "canceled"
            current_period_end = (obj.get("current_period_end") or
                                  (obj.get("items", {}).get("data") or [{}])[0].get("current_period_end"))
            is_canceling = bool(obj.get("cancel_at_period_end") or obj.get("cancel_at"))
            update_user_billing(user["id"],
                plan_status=plan_status,
                trial_ends_at=obj.get("trial_end"),
                current_period_end=current_period_end,
                cancel_at_period_end=is_canceling,
            )

    elif event["type"] in ("customer.subscription.deleted", "customer.subscription.paused"):
        customer_id = obj.get("customer")
        user = get_user_by_stripe_customer(customer_id)
        if user:
            current_period_end = (obj.get("current_period_end") or
                                  (obj.get("items", {}).get("data") or [{}])[0].get("current_period_end"))
            update_user_billing(user["id"],
                plan_status="canceled",
                current_period_end=current_period_end,
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
    native_language: str = ""  # kept for backwards compat, ignored
    job_context: str = "Professional"


@app.post("/coach")
def coach(req: CoachRequest, user_id: int = Depends(_current_user_id)):
    if not ANTHROPIC_API_KEY:
        raise HTTPException(500, "Server is not configured with an Anthropic API key.")

    client = Anthropic(api_key=ANTHROPIC_API_KEY)
    system = COACH_SYSTEM.format(
        job_context=req.job_context,
    )
    response = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=4096,
        system=system,
        messages=[{"role": "user", "content": req.transcript}],
        timeout=90,
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
