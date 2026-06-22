<wizard-report>
# PostHog post-wizard report

The wizard completed a targeted PostHog integration for the Fluent FastAPI backend. The `posthog` SDK was already installed and partially instrumented — the wizard verified the `POSTHOG_API_KEY` and `POSTHOG_HOST` environment variables are set correctly in `.env.local`, then added four missing capture calls to fill gaps in the event coverage.

**Events added in this wizard run:**

| Event Name | Description | File |
|---|---|---|
| `billing_portal_opened` | User opens the Stripe billing portal to manage their subscription | `backend/main.py` |
| `password_changed` | Authenticated user successfully changes their account password | `backend/main.py` |
| `email_changed` | Authenticated user successfully changes their account email address | `backend/main.py` |
| `session_viewed` | User opens a specific coaching session to review its issues | `backend/main.py` |

**Pre-existing events (already instrumented before this run):** `user_signed_up`, `user_logged_in`, `password_reset_requested`, `password_reset_completed`, `account_deleted`, `checkout_started`, `subscription_activated`, `subscription_cancelled`, `subscription_renewed`, `coaching_session_analyzed`, `session_saved`.

## Next steps

We've built a dashboard and five insights to monitor user behavior:

- [Analytics basics (wizard) — Dashboard](https://eu.posthog.com/project/207155/dashboard/764833)
- [New sign-ups](https://eu.posthog.com/project/207155/insights/RUDX7DpB) — weekly sign-up trend (last 90 days)
- [Subscription conversion funnel](https://eu.posthog.com/project/207155/insights/uFpzCUlC) — sign-up → checkout → activated
- [Daily active coaching users](https://eu.posthog.com/project/207155/insights/GeHBpWxC) — DAU on `coaching_session_analyzed`
- [Subscription cancellations](https://eu.posthog.com/project/207155/insights/6mdg5F7i) — weekly churn signal
- [Session activity](https://eu.posthog.com/project/207155/insights/QyvJrFdD) — sessions saved vs. viewed

## Verify before merging

- [ ] Run a full production build (the wizard only verified the files it touched) and fix any lint or type errors introduced by the generated code.
- [ ] Run the test suite — call sites that were rewritten or instrumented may need updated mocks or fixtures.
- [ ] Add `POSTHOG_API_KEY` and `POSTHOG_HOST` to `.env.example` (or any bootstrap script used by collaborators) so they know what to set.

### Agent skill

We've left an agent skill folder in your project at `.claude/skills/integration-fastapi/`. You can use this context for further agent development when using Claude Code. This will help ensure the model provides the most up-to-date approaches for integrating PostHog.

</wizard-report>
