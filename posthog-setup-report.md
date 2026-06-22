<wizard-report>
# PostHog post-wizard report

The wizard has completed a deep integration of PostHog analytics into the Fluent FastAPI backend. The `posthog` Python SDK was installed and a `Posthog` client instance is initialized at startup using environment variables. All 11 business events covering user authentication (email and Google OAuth), billing lifecycle (checkout, activation, renewal, cancellation), coaching core flow, and account management are now captured. User identification via `_posthog.set()` is called on signup to attach `plan_status` as a person property.

| Event | Description | File |
|---|---|---|
| `user_signed_up` | A new user created an account via email/password or Google OAuth | `backend/main.py` |
| `user_logged_in` | An existing user authenticated via email/password or Google OAuth | `backend/main.py` |
| `account_deleted` | A user permanently deleted their account and cancelled any active subscription | `backend/main.py` |
| `password_reset_requested` | A user requested a password reset email | `backend/main.py` |
| `password_reset_completed` | A user successfully reset their password using a reset token | `backend/main.py` |
| `checkout_started` | A user initiated the Stripe checkout flow to subscribe | `backend/main.py` |
| `subscription_activated` | A Stripe checkout session completed and a subscription was created | `backend/main.py` |
| `subscription_cancelled` | A user's subscription was cancelled or paused via Stripe webhook | `backend/main.py` |
| `subscription_renewed` | A subscription invoice was paid, marking a successful billing renewal | `backend/main.py` |
| `coaching_session_analyzed` | A meeting transcript was analyzed by the AI coach and issues were returned | `backend/main.py` |
| `session_saved` | A completed coaching session with transcript and issues was saved | `backend/main.py` |

## Next steps

We've built some insights and a dashboard for you to keep an eye on user behavior, based on the events we just instrumented:

- [Analytics basics (wizard) — Dashboard](https://eu.posthog.com/project/207155/dashboard/764606)
- [New Signups (wizard)](https://eu.posthog.com/project/207155/insights/XIzzWEeq)
- [Signup to Subscription Funnel (wizard)](https://eu.posthog.com/project/207155/insights/fjrLXYXs)
- [Weekly Active Coaches (wizard)](https://eu.posthog.com/project/207155/insights/q45BJioI)
- [Churn Events (wizard)](https://eu.posthog.com/project/207155/insights/QDdZrnmD)
- [Revenue Events (wizard)](https://eu.posthog.com/project/207155/insights/xGZHgxsf)

## Verify before merging

- [x] Run a full production build (the wizard only verified the files it touched) and fix any lint or type errors introduced by the generated code. — `py_compile` passes; no lint/type tooling configured; only changed signature (`upsert_google_user`) has its one caller updated.
- [x] Run the test suite — call sites that were rewritten or instrumented may need updated mocks or fixtures. — No Python test suite exists in the repo, so nothing to run or update.
- [x] Add `POSTHOG_API_KEY` and `POSTHOG_HOST` to `.env.example` (and any bootstrap/onboarding scripts) so collaborators know what to set. — Added to both `/.env.example` and `/backend/.env.example`.
- [ ] Confirm the returning-visitor path also calls identify — the Google OAuth callback identifies on signup, but returning Google login users only capture `user_logged_in` without a `set()` call; consider adding `_posthog.set()` on login too if you want to keep person properties fresh.

### Agent skill

We've left an agent skill folder in your project at `.claude/skills/integration-fastapi/`. You can use this context for further agent development when using Claude Code. This will help ensure the model provides the most up-to-date approaches for integrating PostHog.

</wizard-report>
