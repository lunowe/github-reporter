# app/routes/chat.py
"""
Chat endpoints — SSE streaming + persistence.
"""

import logging

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse

from app.auth import get_activated_user
from app.config import get_settings, Settings
from app.models.api import ChatRequest
from app.services.llm_factory import LLMConfig, infer_provider
from app.services.github_service import GitHubService
from app.services.agent_runner import AgentRunner
from app.services.token_resolver import resolve_github_token
from app.services import chat_store

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chat"])


@router.post("/chat")
async def chat(
    request: ChatRequest,
    user: dict = Depends(get_activated_user),
    settings: Settings = Depends(get_settings),
):
    logger.info("Chat request: query=%r, repo=%r", request.query, request.repo)
    user_id = str(user["_id"])

    # Resolve repo
    repo = request.repo
    if not repo:
        raise HTTPException(status_code=422, detail="Kein Repository ausgewählt.")

    # Viewers: verify repo is in their allowed list
    if user.get("auth_method") == "email":
        allowed_ids = user.get("allowed_repo_ids", [])
        if allowed_ids:
            from app.db import get_db as _get_db
            _db = _get_db()
            proxy_user_id = user.get("proxy_github_user_id", "")
            allowed_repo = await _db.repos.find_one({
                "user_id": proxy_user_id,
                "repo_id": {"$in": allowed_ids},
                "repo_full_name": repo,
            })
            if not allowed_repo:
                raise HTTPException(
                    status_code=403,
                    detail="Kein Zugriff auf dieses Repository.",
                )
        else:
            raise HTTPException(
                status_code=403,
                detail="Kein Zugriff auf Repositories.",
            )

    # Resolve LLM
    model = request.model or settings.default_llm_model
    provider = infer_provider(model)

    llm_config = LLMConfig(provider=provider, model=model, temperature=1)

    token = await resolve_github_token(user)

    github_service = GitHubService(token=token, repo_full_name=repo)
    agent_runner = AgentRunner(llm_config=llm_config, github_service=github_service)

    # Create or reuse chat session
    chat_id = request.chat_id
    if not chat_id:
        chat_doc = await chat_store.create_chat(user_id, repo, title=request.query[:80])
        chat_id = chat_doc["chat_id"]

    # Persist user message
    await chat_store.append_messages(chat_id, user_id, [
        {"role": "user", "content": request.query},
    ])

    history = [{"role": m.role, "content": m.content} for m in request.chat_history]

    async def stream_and_persist():
        import json as _json

        full_response = ""
        tool_calls: list[dict] = []

        async for chunk in agent_runner.run_streaming(query=request.query, chat_history=history):
            yield chunk

            # Parse each SSE line to collect tool calls and final response
            for line in chunk.split("\n"):
                if not line.startswith("data: "):
                    continue
                try:
                    data = _json.loads(line[6:])
                except Exception:
                    continue

                evt_type = data.get("type")
                if evt_type == "tool_call":
                    tool_calls.append({
                        "name": data.get("name", ""),
                        "id": data.get("id", ""),
                        "input": data.get("input", {}),
                        "status": "running",
                    })
                elif evt_type == "tool_result":
                    # Match to the running tool call and update
                    for tc in tool_calls:
                        if tc["name"] == data.get("name") and tc["status"] == "running":
                            tc["output"] = data.get("output", "")
                            tc["status"] = "done"
                            break
                elif evt_type == "status" and data.get("status") == "completed":
                    full_response = data.get("response", "")

        # Persist assistant message with tool calls
        if full_response or tool_calls:
            assistant_msg: dict = {"role": "assistant", "content": full_response}
            if tool_calls:
                assistant_msg["tool_calls"] = tool_calls
            await chat_store.append_messages(chat_id, user_id, [assistant_msg])

    return StreamingResponse(
        stream_and_persist(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "X-Chat-Id": chat_id,
        },
    )


# ── Chat history endpoints ──────────────────────────────────────────────

@router.get("/chats")
async def list_chats(user: dict = Depends(get_activated_user)):
    user_id = str(user["_id"])
    chats = await chat_store.list_chats(user_id)
    return [
        {
            "chat_id": c["chat_id"],
            "title": c.get("title", ""),
            "repo": c.get("repo", ""),
            "updated_at": c.get("updated_at", ""),
        }
        for c in chats
    ]


@router.get("/chats/{chat_id}")
async def get_chat(chat_id: str, user: dict = Depends(get_activated_user)):
    user_id = str(user["_id"])
    doc = await chat_store.get_chat(chat_id, user_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Chat nicht gefunden.")
    return {
        "chat_id": doc["chat_id"],
        "title": doc.get("title", ""),
        "repo": doc.get("repo", ""),
        "messages": doc.get("messages", []),
        "updated_at": doc.get("updated_at", ""),
    }


@router.delete("/chats/{chat_id}")
async def delete_chat(chat_id: str, user: dict = Depends(get_activated_user)):
    user_id = str(user["_id"])
    deleted = await chat_store.delete_chat(chat_id, user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Chat nicht gefunden.")
    return {"status": "deleted"}
