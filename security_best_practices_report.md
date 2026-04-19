# Security Audit Report

## Executive Summary

Audit date: 2026-04-20

I found 10 security findings in the application code:

- 1 Critical
- 4 High
- 3 Medium
- 2 Low

The most urgent issues are:

1. A default and reused `SESSION_SECRET` can enable forged sessions and decryption of stored GitHub tokens if a deployment keeps the shipped default.
2. Viewer accounts can bypass repo scoping on multiple backend endpoints and use the inviter's GitHub token to enumerate or inspect unauthorized repositories.
3. The dashboard cache is keyed only by repo name and is served before authorization, which can leak private repo metadata across users once cached.

I also ran dependency checks:

- `bun audit` in `frontend/`: no known vulnerabilities found
- `pip-audit -r backend/requirements.txt`: no known vulnerabilities found

Those dependency results are useful, but the highest-risk issues here are application-logic flaws, not package CVEs.

## Critical

### GHR-SEC-001

- Rule ID: GHR-SEC-001
- Severity: Critical
- Location: `backend/app/config.py:24`, `backend/app/services/crypto.py:14-19`, `backend/.env.example:12-15`
- Evidence:

```python
# backend/app/config.py
session_secret: str = "change-me-in-production"
```

```python
# backend/app/services/crypto.py
secret = get_settings().session_secret.encode()
key = base64.urlsafe_b64encode(hashlib.sha256(secret).digest())
return Fernet(key)
```

```dotenv
# backend/.env.example
SESSION_SECRET=change-me-in-production
```

- Impact: If a deployment keeps the default secret, an attacker can forge valid session cookies and decrypt stored GitHub access and refresh tokens, leading to full account compromise inside the application.
- Fix: Fail startup unless `SESSION_SECRET` is changed from the default and meets a minimum entropy/length requirement; use separate secrets for session signing and token encryption instead of deriving both from the same value.
- Mitigation: Rotate the secret immediately in every non-local environment and invalidate all existing sessions/tokens after rotation.
- False positive notes: This is only exploitable if a real environment uses the default or a weak shared secret, but the current defaults make that mistake easy.

## High

### GHR-SEC-002

- Rule ID: GHR-SEC-002
- Severity: High
- Location: `backend/app/services/token_resolver.py:32-53`, `backend/app/routes/repos.py:91-137`, `backend/app/routes/dashboard.py:22-111`
- Evidence:

```python
# backend/app/services/token_resolver.py
if user.get("auth_method") == "email":
    proxy_user_id = user.get("proxy_github_user_id")
    ...
    return await _resolve_token_for_github_user(proxy_user)
```

```python
# backend/app/routes/repos.py
@router.get("/repos/available")
async def available_repos(
    user: dict = Depends(get_activated_user),
):
    token = await resolve_github_token(user)
```

```python
# backend/app/routes/dashboard.py
@router.get("/summary")
async def repo_summary(
    repo: str = Query(...),
    user: dict = Depends(get_activated_user),
):
    token = await resolve_github_token(user)
```

- Impact: Invited email/viewer users can call backend APIs directly and use the inviter's GitHub token to enumerate repositories or inspect repo metadata outside their `allowed_repo_ids` scope.
- Fix: Introduce a shared backend authorization check for every repo-targeted endpoint. For viewer users, resolve the requested `repo` against `allowed_repo_ids` before calling `resolve_github_token`. Reject `/api/repos/available` for viewers or filter it to only allowed repos.
- Mitigation: Temporarily disable viewer access to `/api/repos/available`, `/api/dashboard/summary`, and `/api/dashboard/details` until repo-level checks are enforced server-side.
- False positive notes: Frontend route guards do not mitigate this, because a viewer can call the API directly.

### GHR-SEC-003

- Rule ID: GHR-SEC-003
- Severity: High
- Location: `backend/app/routes/dashboard.py:32-37`, `backend/app/services/dashboard_cache.py:14-43`
- Evidence:

```python
# backend/app/routes/dashboard.py
if not refresh:
    cached = await get_cached_summary(repo)
    if cached:
        return {"source": "cache", "summary": cached}
```

```python
# backend/app/services/dashboard_cache.py
doc = await db.dashboard_cache.find_one({"repo": repo})
```

- Impact: Once any user caches a summary for a private repo, any other authenticated user who knows the repo name can read that cached summary without GitHub authorization.
- Fix: Scope cache entries by authorization context, not just `repo`. At minimum include `user_id`; better, only serve cached data after repo authorization succeeds. Consider disabling shared caching for private repos.
- Mitigation: Disable the cache path for authenticated private-repo summaries until authorization is enforced before cache reads.
- False positive notes: This does not require guessing internal IDs; a plain `owner/repo` string is enough.

### GHR-SEC-004

- Rule ID: GHR-SEC-004
- Severity: High
- Location: `backend/app/config.py:51`, `backend/app/main.py:86-93`, `backend/.env.example:32-33`
- Evidence:

```python
# backend/app/config.py
cors_origins: str = "*"
```

```python
# backend/app/main.py
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

```dotenv
# backend/.env.example
CORS_ORIGINS=*
```

- Impact: The default configuration allows credentialed cross-origin access from arbitrary origins, which weakens browser trust boundaries and amplifies CSRF/login-CSRF risk on cookie-authenticated endpoints.
- Fix: Require an explicit allowlist of trusted frontend origins in non-local environments and reject `*` whenever `allow_credentials=True`.
- Mitigation: If the backend is already public, restrict CORS at the reverse proxy immediately while the app-level fix is prepared.
- False positive notes: If production overrides `CORS_ORIGINS` with a strict allowlist, the deployed risk is reduced; the code and example config still make insecure rollout likely.

### GHR-SEC-005

- Rule ID: GHR-SEC-005
- Severity: High
- Location: `backend/app/routes/auth.py:84-112`, `frontend/app/pages/login.vue:19-29`, `frontend/app/pages/auth/callback.vue:23-35`
- Evidence:

```python
# backend/app/routes/auth.py
body = await request.json()
code = body.get("code", "")
...
token_response = await client.post(
    GITHUB_TOKEN_URL,
    data={
        "client_id": settings.github_app_client_id,
        "client_secret": settings.github_app_client_secret,
        "code": code,
        "redirect_uri": callback_url,
    },
)
```

```ts
// frontend/app/pages/login.vue
sessionStorage.setItem("ghr_oauth_state", data.state);
```

```ts
// frontend/app/pages/auth/callback.vue
const storedState = sessionStorage.getItem("ghr_oauth_state");
if (!state || state !== storedState) {
  error.value = "Ungültiger OAuth-State. Bitte erneut versuchen.";
  return;
}
```

- Impact: The backend never validates OAuth `state`, so a malicious site or alternate client can send a valid GitHub `code` directly to `/api/auth/github/exchange` and log a victim browser into an attacker-controlled account.
- Fix: Bind OAuth state to the backend, not just the SPA. Store a signed nonce in an HttpOnly cookie or server-side store, require `{ code, state }`, and reject exchanges where the state does not match.
- Mitigation: Tightening CORS reduces attack reach, but it does not replace backend state validation.
- False positive notes: The frontend state check helps honest browser flows only. It does not protect the backend endpoint from direct requests.

## Medium

### GHR-SEC-006

- Rule ID: GHR-SEC-006
- Severity: Medium
- Location: `backend/app/services/email_service.py:26-93`, `backend/app/services/email_service.py:180-181`
- Evidence:

```python
from jinja2 import Template

_HTML_TEMPLATE = Template("""... {{ run.final_output }} ... {{ step.output }} ...""")
...
html_body = _HTML_TEMPLATE.render(**ctx)
```

- Impact: Automation output, repo-derived text, or LLM-generated text is injected into HTML emails without autoescaping, allowing HTML content injection in notification emails. That can enable phishing links, tracking pixels, or deceptive email content in some clients.
- Fix: Use a Jinja environment with HTML autoescaping enabled, or escape every untrusted field explicitly before rendering. If rich formatting is needed, sanitize it first and keep the allowlist small.
- Mitigation: Prefer sending plain-text-only notifications until HTML escaping is fixed.
- False positive notes: Most email clients block JavaScript, so this is not equivalent to browser XSS, but HTML injection in email is still a real phishing and content-integrity issue.

### GHR-SEC-007

- Rule ID: GHR-SEC-007
- Severity: Medium
- Location: `backend/app/services/invite_service.py:75-96`, `backend/app/services/access_code_service.py:81-128`, `backend/app/services/user_service.py:137-143`, `backend/app/services/user_service.py:264-282`
- Evidence:

```python
# backend/app/services/invite_service.py
invite = await get_invite_by_token(token)
...
user = await create_email_user(...)
...
await db.invites.update_one(
    {"_id": invite["_id"]},
    {"$set": {"redeemed": True, "redeemed_at": now}},
)
```

```python
# backend/app/services/access_code_service.py
code_doc = await db.access_codes.find_one({"code": code_str})
...
await db.access_codes.update_one(
    {"_id": code_doc["_id"]},
    {"$inc": {"used_count": 1}, "$push": {"used_by": {...}}},
)
```

```python
# backend/app/services/user_service.py
await db.users.create_index("email", sparse=True)
```

- Impact: Concurrent requests can redeem the same invite more than once or oversubscribe capped access codes. Because email addresses are not unique, duplicate invited accounts can also be created for the same address.
- Fix: Use atomic `find_one_and_update` conditions (`redeemed=False`, `used_count < max_uses`) or transactions, and add a unique partial index for email-auth users.
- Mitigation: Monitor for duplicate invited users and unexpected `used_count` overruns until the redemption path is made atomic.
- False positive notes: This requires concurrency, but invite links and access codes are exactly the kinds of one-time tokens that should remain single-use under race.

### GHR-SEC-008

- Rule ID: GHR-SEC-008
- Severity: Medium
- Location: `backend/app/routes/auth.py:160-169`, `backend/app/routes/auth.py:194-203`, `backend/app/routes/invites.py:122-131`, `backend/app/auth.py:29-42`, `backend/app/routes/auth.py:209-214`
- Evidence:

```python
response.set_cookie(
    SESSION_COOKIE,
    session_token,
    max_age=SESSION_MAX_AGE,
    httponly=True,
    samesite="lax",
    path="/",
)
```

```python
def create_session_cookie(user_id: str, settings: Settings) -> str:
    return s.dumps(user_id)
```

```python
@router.post("/logout")
async def logout():
    response.delete_cookie(SESSION_COOKIE, path="/")
```

- Impact: Cookies are not marked `Secure`, so they can traverse plain HTTP if deployment is misconfigured. Sessions are also stateless and only contain a signed user ID, so a stolen cookie remains valid until expiry even after logout.
- Fix: Add an environment-driven `secure` flag for TLS deployments, consider the `__Host-` cookie prefix, and add server-side session versioning or revocation so logout and secret rotation can invalidate active sessions immediately.
- Mitigation: Keep `SESSION_MAX_AGE` short until revocation exists, and ensure TLS termination is mandatory in non-local environments.
- False positive notes: `Secure` should stay off in local HTTP development; this is a production-hardening issue, not a local-dev defect.

## Low

### GHR-SEC-009

- Rule ID: GHR-SEC-009
- Severity: Low
- Location: `backend/app/main.py:79-84`
- Evidence:

```python
app = FastAPI(
    title="GitHub Reporter",
    description="Agentic tool to query GitHub repos for project status reports.",
    version="0.3.0",
    lifespan=lifespan,
)
```

- Impact: FastAPI interactive docs and OpenAPI remain enabled by default, which exposes API structure and authenticated endpoints to anyone who can reach the service.
- Fix: Disable `docs_url`, `redoc_url`, and `openapi_url` in production or protect them with auth/network restrictions.
- Mitigation: Block `/docs`, `/redoc`, and `/openapi.json` at the ingress layer until the app config is adjusted.
- False positive notes: This is less severe for internal-only deployments, but still increases attacker reconnaissance value.

### GHR-SEC-010

- Rule ID: GHR-SEC-010
- Severity: Low
- Location: `backend/app/routes/chat.py:54`, `backend/app/services/agent_runner.py:108`, `backend/app/services/agent_runner.py:183`
- Evidence:

```python
logger.info("Chat request: query=%r, repo=%r", request.query, request.repo)
logger.info("Agent run: query=%r", query)
logger.info("Agent run_once: query=%r", query)
```

- Impact: User prompts and automation queries are logged verbatim. In this product, prompts may contain internal repository details, secrets pasted by users, or sensitive operational context.
- Fix: Log request IDs, chat IDs, repo names, and prompt length instead of raw prompt text. Reserve full prompt logging for an explicitly enabled debug mode with short retention.
- Mitigation: Restrict log access and retention immediately if prompt logging must stay temporarily.
- False positive notes: This is a confidentiality/logging issue, not a direct remote exploit.

## Hardening Gaps To Verify At Runtime

These were not directly visible in repo code and should be verified in deployment:

- TLS enforcement and whether cookies are only ever issued over HTTPS
- Reverse-proxy security headers such as CSP and clickjacking protection
- Host header restrictions (`TrustedHostMiddleware` or equivalent edge enforcement)
- Login and invite endpoint rate limiting / brute-force protection at the edge

## Suggested Remediation Order

1. Replace and enforce strong secrets, then rotate sessions/tokens if any environment ever used the default.
2. Fix viewer repo authorization on every repo-targeted backend endpoint and remove the cross-user dashboard cache leak.
3. Lock down CORS and move OAuth `state` validation into the backend.
4. Make invite/access-code redemption atomic and add a unique email constraint for invited accounts.
5. Add HTML autoescaping for emails, secure cookie settings for TLS, and production hardening for docs/logging.
