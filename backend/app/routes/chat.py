"""
Chat endpoints — durable runs over SSE.

POST /api/chat                                          start (or reuse) a chat + new run
GET  /api/chat/{chat_id}/runs/{run_id}/stream           resume an in-flight or recently-terminal run
POST /api/chat/{chat_id}/runs/{run_id}/cancel           publish cancel signal over pub/sub
GET  /api/chats                                         list chats (with active_run if live)
GET  /api/chats/{chat_id}                               fetch chat history (with active_run if live)
DELETE /api/chats/{chat_id}                             cancel any live run and delete
"""

from __future__ import annotations

import asyncio
import logging
from typing import AsyncGenerator

from fastapi import APIRouter, Depends, HTTPException, Header, Query, Request
from fastapi.responses import StreamingResponse

from app.auth import get_activated_user, is_admin
from app.config import get_settings, Settings
from app.models.api import ChatRequest
from app.redis_client import get_redis
from app.services.llm_factory import LLMConfig, infer_provider
from app.services.github_service import GitHubService
from app.services.agent_runner import AgentRunner
from app.services.token_resolver import resolve_github_token
from app.services import chat_store, stream_manager, usage_service
from app.services.stream_manager import (
    RunContext,
    TERMINAL_STATUSES,
    active_run_key,
    meta_key,
)
from app.utils import sse_event, sse_comment

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["chat"])

# Idle keepalive cadence — long enough to avoid spam, short enough to beat
# typical proxy idle timeouts (60s on many CDNs).
KEEPALIVE_INTERVAL_S = 15


@router.post("/chat")
async def chat(
    request: ChatRequest,
    http_request: Request,
    user: dict = Depends(get_activated_user),
    settings: Settings = Depends(get_settings),
):
    logger.info("Chat request: query=%r, repo=%r", request.query, request.repo)
    user_id = str(user["_id"])

    repo = request.repo
    if not repo:
        raise HTTPException(status_code=422, detail="Kein Repository ausgewählt.")

    # Viewers: verify repo is in their allowed list
    if user.get("auth_method") == "email":
        allowed_ids = user.get("allowed_repo_ids", [])
        if not allowed_ids:
            raise HTTPException(status_code=403, detail="Kein Zugriff auf Repositories.")
        from app.db import get_db as _get_db
        proxy_user_id = user.get("proxy_github_user_id", "")
        allowed_repo = await _get_db().repos.find_one({
            "user_id": proxy_user_id,
            "repo_id": {"$in": allowed_ids},
            "repo_full_name": repo,
        })
        if not allowed_repo:
            raise HTTPException(status_code=403, detail="Kein Zugriff auf dieses Repository.")

    # Reject a second concurrent run on the same chat BEFORE we do any
    # expensive LLM/token work. Only applies to existing chats — fresh chats
    # can't have an active run yet.
    if request.chat_id:
        existing_run = await stream_manager.get_active_run_id(request.chat_id)
        if existing_run:
            existing_meta = await stream_manager.get_meta(existing_run)
            if existing_meta and existing_meta.status not in TERMINAL_STATUSES:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "message": "In diesem Chat läuft bereits eine Antwort.",
                        "chat_id": request.chat_id,
                        "run_id": existing_run,
                    },
                )

    existing_chat = await chat_store.get_chat(request.chat_id, user_id) if request.chat_id else None

    # Preserve the chat's original model so a conversation stays on one LLM.
    model = (
        (existing_chat or {}).get("model")
        or request.model
        or settings.default_llm_model
    )
    provider = infer_provider(model)
    llm_config = LLMConfig(provider=provider, model=model, temperature=1)

    # Access gate: suspension + per-user model allow-list are always enforced;
    # the monthly budget is only hard-blocked when enforcement is switched on.
    gate = await usage_service.check_run_allowed(
        user,
        model=model,
        is_admin=is_admin(user, settings),
        default_plan=settings.default_plan,
        enforce_budget=settings.usage_limit_enforced,
    )
    if not gate["allowed"]:
        raise HTTPException(
            status_code=gate.get("status", 403),
            detail={
                "message": gate.get("message", "Zugriff verweigert."),
                "reason": gate.get("reason"),
                "budget_usd": gate.get("budget_usd"),
                "period_cost_usd": gate.get("period_cost_usd"),
            },
        )

    token = await resolve_github_token(user)
    github_service = GitHubService(token=token, repo_full_name=repo)
    agent_runner = AgentRunner(llm_config=llm_config, github_service=github_service)

    # If the client didn't provide a chat_id, or did but the chat doesn't
    # exist, create it now — honoring a client-minted id when present so the
    # UI can address the chat before this response returns.
    if existing_chat:
        chat_id = existing_chat["chat_id"]
    else:
        chat_doc = await chat_store.create_chat(
            user_id, repo, title=request.query[:80], model=model,
            chat_id=request.chat_id,
        )
        chat_id = chat_doc["chat_id"]

    # Persist user message now so a crash before streaming doesn't lose it.
    await chat_store.append_messages(chat_id, user_id, [
        {"role": "user", "content": request.query},
    ])

    history = [{"role": m.role, "content": m.content} for m in request.chat_history]

    async def producer(ctx: RunContext) -> None:
        full_response = ""
        tool_calls: list[dict] = []
        errored: Exception | None = None

        try:
            async for evt_type, data in agent_runner.run_streaming(
                query=request.query,
                chat_history=history,
                cancel_event=ctx.cancel_event,
            ):
                if ctx.cancelled:
                    break

                if evt_type == "token":
                    full_response += data.get("content", "")
                    await ctx.publish("token", data)
                    await ctx.set_partial(full_response)

                elif evt_type == "tool_call":
                    tool_calls.append({
                        "name": data.get("name", ""),
                        "id": data.get("id", ""),
                        "input": data.get("input", {}),
                        "status": "running",
                    })
                    await ctx.publish("tool_call", data)

                elif evt_type == "tool_result":
                    for tc in tool_calls:
                        if tc["name"] == data.get("name") and tc["status"] == "running":
                            tc["output"] = data.get("output", "")
                            tc["status"] = "done"
                            break
                    await ctx.publish("tool_result", data)

                elif evt_type == "status":
                    # Informational; wrapper emits the authoritative terminal status.
                    await ctx.publish("status", data)

        except asyncio.CancelledError:
            raise
        except Exception as e:
            errored = e
            raise
        finally:
            await ctx.set_partial(full_response, force=True)

            if ctx.cancelled:
                msg_status = "cancelled"
            elif errored is not None:
                msg_status = "error"
            else:
                msg_status = "complete"

            # Record token/cost usage for this run (best-effort; never raises).
            usage = agent_runner.usage()
            await usage_service.record_usage(
                user_id=user_id,
                kind="chat",
                chat_id=chat_id,
                repo=repo,
                status=msg_status,
                **usage,
            )

            if full_response or tool_calls:
                msg: dict = {
                    "role": "assistant",
                    "content": full_response,
                    "status": msg_status,
                }
                if tool_calls:
                    msg["tool_calls"] = tool_calls
                try:
                    await chat_store.append_messages(chat_id, user_id, [msg])
                except Exception:
                    logger.exception("Failed to persist assistant message")

    run_id = await stream_manager.start_run(
        chat_id=chat_id,
        user_id=user_id,
        producer=producer,
    )

    return StreamingResponse(
        _sse_stream(run_id, last_event_id=None, http_request=http_request),
        media_type="text/event-stream",
        headers=_sse_headers(chat_id, run_id),
    )


@router.get("/chat/{chat_id}/runs/{run_id}/stream")
async def resume_run(
    chat_id: str,
    run_id: str,
    http_request: Request,
    user: dict = Depends(get_activated_user),
    last_event_id_header: str | None = Header(default=None, alias="Last-Event-ID"),
    last_event_id_query: str | None = Query(default=None, alias="last_event_id"),
):
    user_id = str(user["_id"])

    meta = await stream_manager.get_meta(run_id)
    if not meta:
        # Unknown/expired — client should fall back to loading chat history.
        raise HTTPException(status_code=410, detail="Run expired")
    if meta.user_id != user_id or meta.chat_id != chat_id:
        raise HTTPException(status_code=404, detail="Run nicht gefunden.")

    return StreamingResponse(
        _sse_stream(
            run_id,
            last_event_id=last_event_id_header or last_event_id_query,
            http_request=http_request,
        ),
        media_type="text/event-stream",
        headers=_sse_headers(chat_id, run_id),
    )


@router.post("/chat/{chat_id}/runs/{run_id}/cancel")
async def cancel_run(
    chat_id: str,
    run_id: str,
    user: dict = Depends(get_activated_user),
):
    user_id = str(user["_id"])

    meta = await stream_manager.get_meta(run_id)
    if not meta or meta.user_id != user_id or meta.chat_id != chat_id:
        raise HTTPException(status_code=404, detail="Run nicht gefunden.")

    ok = await stream_manager.request_cancel(run_id)
    return {"cancelled": ok, "status": "cancelling" if ok else meta.status}


@router.get("/chats")
async def list_chats(user: dict = Depends(get_activated_user)):
    user_id = str(user["_id"])
    chats = await chat_store.list_chats(user_id)
    if not chats:
        return []

    active_runs = await _active_runs_for_chats(
        [c["chat_id"] for c in chats], user_id=user_id,
    )

    return [
        {
            "chat_id": c["chat_id"],
            "title": c.get("title", ""),
            "repo": c.get("repo", ""),
            "model": c.get("model"),
            "updated_at": c.get("updated_at", ""),
            "active_run": ar,
        }
        for c, ar in zip(chats, active_runs)
    ]


@router.get("/chats/{chat_id}")
async def get_chat(chat_id: str, user: dict = Depends(get_activated_user)):
    user_id = str(user["_id"])
    doc = await chat_store.get_chat(chat_id, user_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Chat nicht gefunden.")

    [active_run] = await _active_runs_for_chats([chat_id], user_id=user_id, include_started_at=True)

    return {
        "chat_id": doc["chat_id"],
        "title": doc.get("title", ""),
        "repo": doc.get("repo", ""),
        "model": doc.get("model"),
        "messages": doc.get("messages", []),
        "updated_at": doc.get("updated_at", ""),
        "active_run": active_run,
    }


@router.delete("/chats/{chat_id}")
async def delete_chat(chat_id: str, user: dict = Depends(get_activated_user)):
    user_id = str(user["_id"])

    # Cancel any live run first so the producer doesn't race the Mongo delete.
    active_run_id = await stream_manager.get_active_run_id(chat_id)
    if active_run_id:
        await stream_manager.request_cancel(active_run_id)

    deleted = await chat_store.delete_chat(chat_id, user_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Chat nicht gefunden.")
    return {"status": "deleted"}


# ── Helpers ───────────────────────────────────────────────────────────────

def _sse_headers(chat_id: str, run_id: str) -> dict[str, str]:
    return {
        "Cache-Control": "no-cache",
        "Connection": "keep-alive",
        "X-Accel-Buffering": "no",
        "X-Chat-Id": chat_id,
        "X-Run-Id": run_id,
    }


async def _active_runs_for_chats(
    chat_ids: list[str],
    *,
    user_id: str,
    include_started_at: bool = False,
) -> list[dict | None]:
    """
    Fetch active-run summaries for a batch of chat ids in 2 Redis round-trips
    (MGET + pipelined HGETALLs) instead of 2 × N.
    """
    if not chat_ids:
        return []

    redis = get_redis()
    run_ids = await redis.mget([active_run_key(cid) for cid in chat_ids])

    metas: dict[str, dict] = {}
    to_fetch = [rid for rid in run_ids if rid]
    if to_fetch:
        pipe = redis.pipeline()
        for rid in to_fetch:
            pipe.hgetall(meta_key(rid))
        results = await pipe.execute()
        for rid, meta in zip(to_fetch, results):
            if meta:
                metas[rid] = meta

    def _build(run_id: str | None) -> dict | None:
        if not run_id:
            return None
        meta = metas.get(run_id)
        if not meta or meta.get("user_id") != user_id:
            return None
        if meta.get("status") in TERMINAL_STATUSES:
            return None
        out: dict = {"run_id": run_id, "status": meta.get("status", "")}
        if include_started_at:
            out["started_at"] = meta.get("started_at", "")
        return out

    return [_build(rid) for rid in run_ids]


async def _sse_stream(
    run_id: str,
    *,
    last_event_id: str | None,
    http_request: Request,
) -> AsyncGenerator[bytes, None]:
    """
    Merge the event stream and a keepalive ticker onto a single queue so
    comments go out even when the producer is silent (otherwise middleboxes
    with 60s idle timeouts would drop the connection).
    """
    queue: asyncio.Queue[bytes | None] = asyncio.Queue()
    DONE = None  # sentinel

    async def disconnect_check() -> bool:
        try:
            return await http_request.is_disconnected()
        except Exception:
            return False

    async def pump_events() -> None:
        try:
            async for event_id, evt_type, data in stream_manager.subscribe(
                run_id, last_event_id=last_event_id, disconnect_check=disconnect_check,
            ):
                await queue.put(sse_event(data, event_id=event_id, event_type=evt_type).encode("utf-8"))
                if evt_type == "status" and data.get("status") in TERMINAL_STATUSES:
                    break
        finally:
            await queue.put(DONE)

    async def pump_keepalives() -> None:
        frame = sse_comment("keepalive").encode("utf-8")
        try:
            while True:
                await asyncio.sleep(KEEPALIVE_INTERVAL_S)
                await queue.put(frame)
        except asyncio.CancelledError:
            pass

    events_task = asyncio.create_task(pump_events())
    ka_task = asyncio.create_task(pump_keepalives())

    try:
        while True:
            item = await queue.get()
            if item is DONE:
                return
            yield item
    finally:
        ka_task.cancel()
        events_task.cancel()
        for t in (ka_task, events_task):
            try:
                await t
            except (asyncio.CancelledError, Exception):
                pass
