# GitHub Reporter

An AI assistant for project managers and team leads who need a clear view of what's happening across their GitHub repositories — without reading every PR, commit, or pipeline run themselves. Ask in natural language, get answers grounded in live repository data.

Built with a **FastAPI** backend, **Nuxt 4** frontend, and **LlamaIndex** agents that can talk to Google Gemini, OpenAI, or Anthropic Claude.

> The UI and agent responses are in **German** — the target audience is German-speaking PMs and team leads.

---

## Live deployment

The app is currently hosted on **Railway** behind an invite-only access wall. Two ways to get in:

- **Access code** — single- or multi-use code issued by the admin. Redeem under `/activate` after GitHub login.
- **Email invite** — admin sends a magic-link invite scoped to specific repos. Creates a "viewer" account with read-only access to the assigned repos (no GitHub auth required).

If you need a code or invite, ping me directly.

---

## What it can do today

### Chat with the agent
- Natural-language questions, answered with live data fetched through tools
- Real-time SSE streaming with visible tool calls (you see what the agent is doing)
- Durable runs backed by Redis — reconnect after a refresh and keep streaming
- Chat history is persisted and searchable per user

### Agent capabilities (tools)

| Area | Tools |
|---|---|
| **Repo overview** | summary, contributors, languages, latest release |
| **Commits** | list/filter by date, author, branch |
| **Pull requests** | open/closed PRs with full detail views |
| **Issues** | list, filter, inspect with labels, assignees, comments |
| **CI/CD** | GitHub Actions workflow run status |
| **Code browsing** | walk directories, read files |
| **Branch comparison** | ahead/behind, changed files between two branches |
| **Search** | full-text across code and issues |
| **Containers** | GHCR images, tags, and which commit produced an image |

### Beyond chat
- **Multi-repo dashboard** — cached at-a-glance stats per connected repo
- **Automations** — chained-prompt workflows on a cron schedule; results delivered via SMTP email. Steps can reference earlier step outputs with `{{stepN.output}}` for templated reports.
- **Admin tools** — user management, repo-scoped viewer invites, access code issuance
- **Multi-LLM** — switch provider (Gemini / OpenAI / Anthropic) per session

---

## What it can't do (yet)

- **Read-only on GitHub.** The agent doesn't open issues, comment on PRs, merge, or push.
- **German only.** UI strings and agent prompt are German. No i18n layer yet.
- **Email-only notifications.** No Slack, Teams, Discord, or webhook delivery for automations.
- **Single admin.** Admin is identified by one configured GitHub username — no roles, no orgs, no teams.
- **Polling, not events.** No GitHub webhook ingestion; everything is fetched on demand (cached where it makes sense).
- **No conversation export.** Can't share, fork, or export a chat as Markdown/PDF.
- **No code-aware retrieval.** The agent reads files on demand but doesn't index/embed the repo, so "semantic" code search across a large repo is limited to GitHub's own search.
- **Single-tenant.** Designed for one team / one admin, not as a multi-tenant SaaS.

---

## Possible improvements

A non-exhaustive backlog, in rough priority order:

- English / i18n switch
- Slack & Teams delivery for automations
- GitHub webhooks → push-style "what changed since you last looked" digests
- Write actions: comment on PR, open issue, request review (gated behind explicit user opt-in)
- Org/team RBAC instead of single-admin
- Repo-wide semantic search (embedded code index) for "where does X live?" questions
- Chat export (Markdown / PDF) and shareable read-only links
- Diff-style release summaries between two tags
- Run-cost visibility per chat (LLM token spend)

---

## Local setup

The production deployment runs on Railway; for local development the simplest path is Docker.

**Prerequisites**
- Docker + docker-compose
- A [GitHub App](https://github.com/settings/apps) (OAuth enabled, installed on the repos you want to query)
- At least one LLM API key (Gemini, OpenAI, or Anthropic)
- *(Optional)* SMTP credentials if you want automations to send email

**1. Configure**

```bash
cp backend/.env.example backend/.env
```

Fill in at minimum:

```env
GITHUB_APP_CLIENT_ID=...
GITHUB_APP_CLIENT_SECRET=...
GITHUB_APP_SLUG=your-app-slug
ADMIN_GITHUB_LOGIN=your-github-username   # you become the admin
SESSION_SECRET=...                        # python -c "import secrets; print(secrets.token_urlsafe(32))"
APP_URL=http://localhost:3200
GOOGLE_API_KEY=...                        # or OPENAI_API_KEY / ANTHROPIC_API_KEY
```

GitHub App callback URL: `http://localhost:3200/auth/callback`.
Permissions needed: Contents, Issues, Pull requests, Actions, Metadata (all read-only).

**2. Run**

```bash
docker-compose up --build
```

Brings up MongoDB, Redis, the FastAPI backend, and the Nuxt frontend.

**3. Use**

Open **http://localhost:3200**, sign in with GitHub. Since you set `ADMIN_GITHUB_LOGIN` to your own username, your account auto-activates — no access code needed. Connect a repo from the settings page and start chatting.

### Default ports

| Service | Port | Override |
|---|---|---|
| Frontend | `3200` | `GHR_FRONTEND_PORT` |
| Backend | `8200` | `GHR_BACKEND_PORT` |
| MongoDB | `27018` | `GHR_MONGO_PORT` |

### Without Docker

```bash
# Backend
cd backend && python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
# Requires MongoDB and Redis running locally

# Frontend
cd frontend && bun install && bun run dev
```

See `backend/.env.example` for the full list of environment variables (SMTP, scheduler timezone, CORS, etc.).

---

## Stack

| Layer | |
|---|---|
| Frontend | Nuxt 4, Vue 3, TypeScript, TailwindCSS, shadcn-nuxt |
| Backend | FastAPI, Python 3.11, LlamaIndex, PyGithub, APScheduler |
| Data | MongoDB (state), Redis (streaming + cancel pub/sub) |
| LLMs | Google Gemini, OpenAI, Anthropic Claude |
| Hosting | Railway (production), Docker Compose (local) |

---

## License

Proprietary. All rights reserved.
