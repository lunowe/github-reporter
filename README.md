# GitHub Reporter

An AI-powered tool that gives project managers and team leads a clear, real-time overview of their GitHub repositories. Ask questions in natural language and get intelligent answers based on live repository data — commits, pull requests, issues, CI/CD status, code browsing, and more.

Built with a **FastAPI** backend, **Nuxt 4** frontend, and **LlamaIndex agents** that support multiple LLM providers (Google Gemini, OpenAI, Anthropic Claude).

> **Note:** The UI and agent responses are in **German**, designed for German-speaking teams.

---

## Features

- **Natural Language Chat** — Ask questions about your repositories and get AI-generated answers grounded in real GitHub data
- **Multi-Repo Support** — Connect multiple repositories and switch between them
- **Dashboard** — At-a-glance overview with quick stats for all connected repos
- **Live Streaming** — Responses stream in real-time via SSE, including tool call transparency
- **Multiple LLM Providers** — Choose between Google Gemini, OpenAI GPT, or Anthropic Claude
- **GitHub OAuth** — Secure authentication via GitHub Apps (no personal tokens needed)
- **Chat History** — Conversations are persisted and searchable

### What the Agent Can Do

| Capability | Description |
|---|---|
| **Commits** | List, filter, and analyze recent commits by date, author, or branch |
| **Pull Requests** | Browse open/closed PRs with full detail views |
| **Issues** | List and inspect issues with labels, assignees, and comments |
| **CI/CD** | Check GitHub Actions workflow run status |
| **Code Browsing** | Browse directories and read file contents directly |
| **Branch Comparison** | Compare two branches (ahead/behind, changed files) |
| **Contributors** | View top contributors and their activity |
| **Search** | Full-text search across code and issues |
| **Repo Summary** | Quick overview — stars, branches, languages, latest release |

---

## Tech Stack

| Layer | Technology |
|---|---|
| **Frontend** | Nuxt 4 (Vue 3), TypeScript, TailwindCSS, shadcn-nuxt, Bun |
| **Backend** | FastAPI, Python 3.11, LlamaIndex, PyGithub |
| **Database** | MongoDB (via Motor async driver) |
| **LLM Providers** | Google Gemini, OpenAI, Anthropic Claude |
| **Infrastructure** | Docker, docker-compose |

---

## Prerequisites

- **Docker & docker-compose** (recommended for quickest setup)
- A [**GitHub App**](https://github.com/settings/apps) with OAuth enabled
- At least one **LLM API key** (Gemini, OpenAI, or Anthropic)

For local development without Docker:
- Python 3.11+
- Node.js 22+ or [Bun](https://bun.sh)

---

## Quick Start (Docker)

### 1. Clone the repository

```bash
git clone https://github.com/your-org/github-reporter.git
cd github-reporter
```

### 2. Create a GitHub App

1. Go to [GitHub Settings > Developer settings > GitHub Apps](https://github.com/settings/apps)
2. Create a new GitHub App with:
   - **Callback URL:** `http://localhost:3200/auth/callback`
   - **Permissions:** Repository contents (read), Issues (read), Pull requests (read), Actions (read), Metadata (read)
3. Note the **Client ID** and generate a **Client Secret**
4. Install the App on the repositories you want to analyze

### 3. Configure environment variables

```bash
cp backend/.env.example backend/.env
```

Edit `backend/.env` and fill in your values:

```env
# GitHub App (required)
GITHUB_APP_CLIENT_ID=your_client_id
GITHUB_APP_CLIENT_SECRET=your_client_secret
GITHUB_APP_SLUG=your-app-slug

# Session secret (required — generate a secure one)
# python -c "import secrets; print(secrets.token_urlsafe(32))"
SESSION_SECRET=change-me-in-production

# Frontend URL for OAuth redirect
APP_URL=http://localhost:3200

# LLM API keys (set at least one)
GOOGLE_API_KEY=
OPENAI_API_KEY=
ANTHROPIC_API_KEY=

# LLM defaults
DEFAULT_LLM_PROVIDER=gemini
DEFAULT_LLM_MODEL=gemini-3-flash-preview

# MongoDB (overridden by docker-compose, keep default for local dev)
MONGODB_URL=mongodb://localhost:27017
MONGODB_DB_NAME=github_reporter
```

### 4. Start the stack

```bash
docker-compose up --build
```

### 5. Open the app

Navigate to **http://localhost:3200**, log in with GitHub, connect a repo, and start chatting.

### Default Ports

| Service | Port | Override Variable |
|---|---|---|
| Frontend | `3200` | `GHR_FRONTEND_PORT` |
| Backend API | `8200` | `GHR_BACKEND_PORT` |
| MongoDB | `27018` | `GHR_MONGO_PORT` |

Override ports via environment variables:

```bash
GHR_FRONTEND_PORT=4000 GHR_BACKEND_PORT=9000 docker-compose up --build
```

---

## Local Development (without Docker)

### Backend

```bash
cd backend
python -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Make sure MongoDB is running (e.g. via Docker):
# docker run -d -p 27017:27017 mongo:8.0

uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

The API will be available at `http://localhost:8000` with interactive docs at `/docs`.

### Frontend

```bash
cd frontend
bun install        # or: npm install
bun run dev        # or: npm run dev
```

The frontend will be available at `http://localhost:3000`.

> **Note:** In local dev the frontend proxies `/api/*` requests to the backend. Set `NUXT_BACKEND_URL` if your backend runs on a non-default port.

---

## Project Structure

```
github-reporter/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI entrypoint
│   │   ├── config.py            # Environment configuration
│   │   ├── auth.py              # Session & OAuth verification
│   │   ├── db.py                # MongoDB connection
│   │   ├── models/              # Pydantic request/response schemas
│   │   ├── routes/              # API endpoints (auth, chat, repos, dashboard)
│   │   ├── services/            # Business logic (LLM, GitHub, caching, crypto)
│   │   └── tools/               # LlamaIndex agent tools (commits, PRs, issues, ...)
│   ├── requirements.txt
│   ├── Dockerfile
│   └── .env.example
├── frontend/
│   ├── app/
│   │   ├── pages/               # Vue pages (dashboard, chat, settings, login)
│   │   ├── components/          # UI components (chat, dashboard, layout)
│   │   ├── composables/         # Vue composition hooks (auth, chat, repos, API)
│   │   └── types/               # TypeScript interfaces
│   ├── server/routes/           # API proxy to backend
│   ├── nuxt.config.ts
│   ├── package.json
│   └── Dockerfile
└── docker-compose.yml
```

---

## API Overview

| Method | Endpoint | Description |
|---|---|---|
| `GET` | `/health` | Health check |
| `GET` | `/api/auth/github-url` | Get GitHub OAuth URL |
| `POST` | `/api/auth/github/exchange` | Exchange OAuth code for session |
| `POST` | `/api/auth/logout` | Log out |
| `GET` | `/api/auth/me` | Current user profile |
| `GET` | `/api/repos` | List connected repos |
| `POST` | `/api/repos` | Connect a new repo |
| `GET` | `/api/repos/available` | List repos available via GitHub App |
| `DELETE` | `/api/repos/{repo_id}` | Disconnect a repo |
| `POST` | `/api/chat` | Send a chat message (SSE stream) |
| `GET` | `/api/chats` | List chat sessions |
| `GET` | `/api/chats/{chat_id}` | Get chat history |
| `DELETE` | `/api/chats/{chat_id}` | Delete a chat |
| `GET` | `/api/dashboard/summary` | Cached repo summary |
| `GET` | `/api/dashboard/details` | Detailed repo statistics |

---

## Configuration Reference

All configuration is done via `backend/.env`. See [`backend/.env.example`](backend/.env.example) for the full template.

| Variable | Required | Description |
|---|---|---|
| `GITHUB_APP_CLIENT_ID` | Yes | OAuth Client ID from your GitHub App |
| `GITHUB_APP_CLIENT_SECRET` | Yes | OAuth Client Secret |
| `GITHUB_APP_SLUG` | Yes | Your GitHub App's URL slug |
| `SESSION_SECRET` | Yes | Secret for signing cookies & encrypting tokens |
| `APP_URL` | Yes | Frontend URL (for OAuth callback redirect) |
| `GOOGLE_API_KEY` | * | Google Gemini API key |
| `OPENAI_API_KEY` | * | OpenAI API key |
| `ANTHROPIC_API_KEY` | * | Anthropic Claude API key |
| `DEFAULT_LLM_PROVIDER` | No | Default provider: `gemini`, `openai`, or `anthropic` |
| `DEFAULT_LLM_MODEL` | No | Default model name |
| `MONGODB_URL` | No | MongoDB connection string (default: `mongodb://localhost:27017`) |
| `MONGODB_DB_NAME` | No | Database name (default: `github_reporter`) |
| `CORS_ORIGINS` | No | Allowed origins, comma-separated (default: `*`) |

\* At least one LLM API key is required.

---

## License

This project is proprietary. All rights reserved.
