"""
Durable chat runs on Redis.

Each chat turn becomes a "run":
  * a background asyncio.Task drives the agent and XADDs events to a Redis Stream
  * any number of HTTP subscribers can tail the stream (or replay from a Last-Event-ID)
  * cancel travels over a pub/sub channel so any worker can stop any run

Redis keys
----------
run:{run_id}:events   (Stream)   SSE events — XADD id becomes our sequence id
run:{run_id}:meta     (Hash)     status, chat_id, user_id, worker_id, timestamps
chat:{chat_id}:active_run  (Str) current active run_id, cleared at terminal
run:cancel            (channel)  pub/sub — payload is the run_id to cancel

Lifecycles
----------
* running   → producer is alive, heartbeating
* completed → clean finish
* cancelled → user cancel
* error     → exception during generation
* orphaned  → producer went away without publishing a terminal event (stale heartbeat)
Terminal states (completed/cancelled/error/orphaned) carry a TTL and are replayable
until they expire.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import AsyncGenerator, AsyncIterator, Awaitable, Callable, Optional

from redis.asyncio import Redis

from app.config import get_settings
from app.redis_client import get_redis

logger = logging.getLogger(__name__)


class RunStatus:
    """Canonical run status values. Used in Redis meta, SSE events, and persisted messages."""
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"
    ERROR = "error"
    ORPHANED = "orphaned"


TERMINAL_STATUSES = frozenset({
    RunStatus.COMPLETED,
    RunStatus.CANCELLED,
    RunStatus.ERROR,
    RunStatus.ORPHANED,
})

CANCEL_CHANNEL = "run:cancel"

# Random suffix identifies this worker process (crash detection / debugging).
WORKER_ID = f"{int(time.time())}-{uuid.uuid4().hex[:6]}"

# Delete active_run pointer only if it still points at our run_id — prevents a
# late-finishing run from clobbering a pointer that already moved on.
_CAS_DEL_ACTIVE_RUN = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""


def events_key(run_id: str) -> str:
    return f"run:{run_id}:events"


def meta_key(run_id: str) -> str:
    return f"run:{run_id}:meta"


def active_run_key(chat_id: str) -> str:
    return f"chat:{chat_id}:active_run"


@dataclass
class RunMeta:
    run_id: str
    chat_id: str
    user_id: str
    status: str
    worker_id: str
    started_at: str
    updated_at: str
    # Terminal event sequence id (XADD id) — lets callers skip replay when exhausted.
    terminal_event_id: Optional[str] = None
    partial_response: str = ""
    error: str = ""


@dataclass
class _LocalRun:
    """A run owned by THIS worker — lets us cancel its task on signal."""
    run_id: str
    task: asyncio.Task
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)


# Per-worker state
_local_runs: dict[str, _LocalRun] = {}
_cancel_subscriber_task: Optional[asyncio.Task] = None


async def start_run(
    *,
    chat_id: str,
    user_id: str,
    producer: Callable[["RunContext"], Awaitable[None]],
) -> str:
    """
    Kick off a new run and return its run_id immediately. The `producer` coroutine
    gets a RunContext with `publish(...)` and a cancel_event it must honor.
    """
    redis = get_redis()
    run_id = f"run_{uuid.uuid4().hex[:16]}"
    now = _now_iso()
    ttl = get_settings().run_ttl_seconds * 2  # doubled while running; tightened on terminal

    pipe = redis.pipeline()
    pipe.hset(
        meta_key(run_id),
        mapping={
            "run_id": run_id,
            "chat_id": chat_id,
            "user_id": user_id,
            "status": RunStatus.RUNNING,
            "worker_id": WORKER_ID,
            "started_at": now,
            "updated_at": now,
            "heartbeat_at": str(time.time()),
            "partial_response": "",
            "error": "",
        },
    )
    pipe.expire(meta_key(run_id), ttl)
    pipe.set(active_run_key(chat_id), run_id, ex=ttl)
    await pipe.execute()

    cancel_event = asyncio.Event()
    ctx = RunContext(
        run_id=run_id,
        chat_id=chat_id,
        user_id=user_id,
        cancel_event=cancel_event,
    )

    task = asyncio.create_task(_producer_wrapper(ctx, producer))
    _local_runs[run_id] = _LocalRun(run_id=run_id, task=task, cancel_event=cancel_event)

    logger.info("Run started: run_id=%s chat_id=%s", run_id, chat_id)
    return run_id


async def get_meta(run_id: str) -> Optional[RunMeta]:
    redis = get_redis()
    raw = await redis.hgetall(meta_key(run_id))
    if not raw:
        return None
    return RunMeta(
        run_id=raw.get("run_id", run_id),
        chat_id=raw.get("chat_id", ""),
        user_id=raw.get("user_id", ""),
        status=raw.get("status", RunStatus.RUNNING),
        worker_id=raw.get("worker_id", ""),
        started_at=raw.get("started_at", ""),
        updated_at=raw.get("updated_at", ""),
        terminal_event_id=raw.get("terminal_event_id") or None,
        partial_response=raw.get("partial_response", ""),
        error=raw.get("error", ""),
    )


async def get_active_run_id(chat_id: str) -> Optional[str]:
    redis = get_redis()
    run_id = await redis.get(active_run_key(chat_id))
    return run_id


async def subscribe(
    run_id: str,
    *,
    last_event_id: str | None = None,
    disconnect_check: Optional[Callable[[], Awaitable[bool]]] = None,
) -> AsyncGenerator[tuple[str, str, dict], None]:
    """
    Yield (event_id, event_type, data_dict) for a given run.

    - Replays buffered events strictly newer than `last_event_id` first.
    - Then tails live events until the run reaches a terminal status.
    - Cooperatively checks `disconnect_check()` between reads so a closed client
      connection terminates the generator promptly (frees Redis connection).

    If the run is unknown/expired, the generator finishes immediately.
    """
    redis = get_redis()

    meta = await get_meta(run_id)
    if not meta:
        return

    # 1) Replay buffered events strictly after last_event_id
    replay_start = _exclusive_start(last_event_id)
    async for event_id, evt_type, data in _range_events(redis, run_id, replay_start, "+"):
        yield event_id, evt_type, data
        last_event_id = event_id
        if disconnect_check and await disconnect_check():
            return

    # If the run is already terminal, we're done after the replay.
    meta = await get_meta(run_id)
    if not meta or meta.status in TERMINAL_STATUSES:
        return

    # 2) Tail live events until terminal — XREAD blocks server-side up to 2s, then
    # we loop so we can check for disconnects and orphan detection.
    cursor = last_event_id or "0"
    settings = get_settings()
    orphan_threshold = settings.run_heartbeat_seconds * 3

    while True:
        if disconnect_check and await disconnect_check():
            return

        resp = await redis.xread({events_key(run_id): cursor}, block=2000, count=50)
        if resp:
            # resp = [(stream_key, [(id, {fields})...])]
            for _stream, entries in resp:
                for event_id, fields in entries:
                    evt_type = fields.get("type", "message")
                    raw_data = fields.get("data", "{}")
                    try:
                        data = json.loads(raw_data)
                    except Exception:
                        data = {"raw": raw_data}
                    yield event_id, evt_type, data
                    cursor = event_id
                    if evt_type == "status" and data.get("status") in TERMINAL_STATUSES:
                        return

        # No events this tick — liveness + orphan check in a single round-trip.
        status, hb_raw = await redis.hmget(meta_key(run_id), "status", "heartbeat_at")
        if status is None:
            return  # meta expired
        if status in TERMINAL_STATUSES:
            return

        try:
            hb = float(hb_raw) if hb_raw else 0.0
        except ValueError:
            hb = 0.0
        if hb and (time.time() - hb) > orphan_threshold:
            await _mark_orphaned(run_id)
            synthetic = {
                "type": "status",
                "status": RunStatus.ORPHANED,
                "error": "Der Server hat die Verbindung zu dieser Antwort verloren.",
            }
            event_id = await _append_event(redis, run_id, "status", synthetic)
            yield event_id, "status", synthetic
            return


async def request_cancel(run_id: str) -> bool:
    """Publish a cancel request. Returns False if the run is already terminal."""
    redis = get_redis()
    meta = await get_meta(run_id)
    if not meta:
        return False
    if meta.status in TERMINAL_STATUSES:
        return False
    await redis.publish(CANCEL_CHANNEL, run_id)
    return True


async def start_cancel_subscriber() -> None:
    """Launch the per-worker pub/sub listener that honors cancel requests."""
    global _cancel_subscriber_task
    if _cancel_subscriber_task is not None and not _cancel_subscriber_task.done():
        return
    _cancel_subscriber_task = asyncio.create_task(_cancel_subscriber_loop())


async def stop_cancel_subscriber() -> None:
    global _cancel_subscriber_task
    if _cancel_subscriber_task is None:
        return
    _cancel_subscriber_task.cancel()
    try:
        await _cancel_subscriber_task
    except (asyncio.CancelledError, Exception):
        pass
    _cancel_subscriber_task = None


async def _cancel_subscriber_loop() -> None:
    redis = get_redis()
    pubsub = redis.pubsub()
    await pubsub.subscribe(CANCEL_CHANNEL)
    logger.info("Cancel subscriber active (worker=%s)", WORKER_ID)
    try:
        async for message in pubsub.listen():
            if message is None:
                continue
            if message.get("type") != "message":
                continue
            run_id = message.get("data") or ""
            if not run_id:
                continue
            local = _local_runs.get(run_id)
            if local:
                logger.info("Cancel signal received for local run %s", run_id)
                local.cancel_event.set()
    except asyncio.CancelledError:
        pass
    except Exception:
        logger.exception("Cancel subscriber crashed")
    finally:
        try:
            await pubsub.unsubscribe(CANCEL_CHANNEL)
            await pubsub.aclose()
        except Exception:
            pass


async def shutdown_local_runs() -> None:
    """Mark every run owned by this worker as cancelled and wait for cleanup."""
    if not _local_runs:
        return
    logger.warning("Shutting down with %d active runs — cancelling", len(_local_runs))
    for local in list(_local_runs.values()):
        local.cancel_event.set()
    # Allow producers a moment to run their finally blocks.
    await asyncio.gather(
        *(local.task for local in list(_local_runs.values())),
        return_exceptions=True,
    )


# Rate-limit for set_partial writes — only persist when the snapshot has
# grown by at least this many characters since the last write.
_PARTIAL_WRITE_THRESHOLD = 200


class RunContext:
    """Handed to the producer; exposes publish() and a cancel_event."""

    def __init__(self, *, run_id: str, chat_id: str, user_id: str, cancel_event: asyncio.Event):
        self.run_id = run_id
        self.chat_id = chat_id
        self.user_id = user_id
        self.cancel_event = cancel_event
        self._partial_len_persisted = 0

    @property
    def cancelled(self) -> bool:
        return self.cancel_event.is_set()

    async def publish(self, evt_type: str, data: dict) -> str:
        """Append an event to the run's stream."""
        return await _append_event(get_redis(), self.run_id, evt_type, data)

    async def set_partial(self, text: str, *, force: bool = False) -> None:
        """
        Persist a snapshot of the running response so reconnecting clients can
        rehydrate without replaying every token. Rate-limited by default; pass
        `force=True` from finally blocks to always flush.
        """
        if not force and (len(text) - self._partial_len_persisted) < _PARTIAL_WRITE_THRESHOLD:
            return
        self._partial_len_persisted = len(text)
        try:
            await get_redis().hset(meta_key(self.run_id), "partial_response", text)
        except Exception:
            logger.debug("Failed to update partial_response", exc_info=True)


async def _producer_wrapper(
    ctx: RunContext,
    producer: Callable[[RunContext], Awaitable[None]],
) -> None:
    """
    Run the producer, heartbeating periodically. On any terminal signal we write
    a `status` event to the stream and mark the meta accordingly.
    """
    hb_task = asyncio.create_task(_heartbeat_loop(ctx.run_id, ctx.cancel_event))
    status = RunStatus.COMPLETED
    err_msg = ""

    try:
        # Producer must honor ctx.cancel_event. Returning None == clean completion.
        await producer(ctx)
        if ctx.cancelled:
            status = RunStatus.CANCELLED
    except asyncio.CancelledError:
        status = RunStatus.CANCELLED
        raise
    except Exception as e:
        logger.exception("Run %s failed", ctx.run_id)
        status = RunStatus.ERROR
        err_msg = str(e) or "Unbekannter Fehler"
    finally:
        hb_task.cancel()
        try:
            await hb_task
        except Exception:
            pass

        redis = get_redis()
        partial_response = await redis.hget(meta_key(ctx.run_id), "partial_response") or ""

        terminal_payload: dict = {
            "type": "status",
            "status": status,
            "response": partial_response,
        }
        if err_msg:
            terminal_payload["error"] = err_msg
        terminal_event_id = await _append_event(redis, ctx.run_id, "status", terminal_payload)

        # Batch terminal meta write + TTLs + CAS-delete of the active-run pointer.
        ttl = get_settings().run_ttl_seconds
        pipe = redis.pipeline()
        pipe.hset(
            meta_key(ctx.run_id),
            mapping={
                "status": status,
                "updated_at": _now_iso(),
                "terminal_event_id": terminal_event_id,
                "error": err_msg,
            },
        )
        pipe.expire(meta_key(ctx.run_id), ttl)
        pipe.expire(events_key(ctx.run_id), ttl)
        pipe.eval(_CAS_DEL_ACTIVE_RUN, 1, active_run_key(ctx.chat_id), ctx.run_id)
        try:
            await pipe.execute()
        except Exception:
            logger.exception("Terminal cleanup failed for %s", ctx.run_id)

        _local_runs.pop(ctx.run_id, None)
        logger.info(
            "Run %s terminal: status=%s chars=%d",
            ctx.run_id, status, len(partial_response),
        )


async def _heartbeat_loop(run_id: str, cancel_event: asyncio.Event) -> None:
    redis = get_redis()
    interval = get_settings().run_heartbeat_seconds
    try:
        while not cancel_event.is_set():
            try:
                await redis.hset(meta_key(run_id), "heartbeat_at", str(time.time()))
            except Exception:
                logger.exception("Heartbeat failed for %s", run_id)
            try:
                await asyncio.wait_for(cancel_event.wait(), timeout=interval)
            except asyncio.TimeoutError:
                continue
            else:
                return
    except asyncio.CancelledError:
        pass


async def _append_event(redis: Redis, run_id: str, evt_type: str, data: dict) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    # maxlen caps the buffer at ~5000 events per run; tokens are tiny so this
    # covers very long agent conversations with comfortable margin.
    event_id = await redis.xadd(
        events_key(run_id),
        {"type": evt_type, "data": payload},
        maxlen=5000,
        approximate=True,
    )
    return event_id


async def _range_events(
    redis: Redis,
    run_id: str,
    start: str,
    end: str,
) -> AsyncIterator[tuple[str, str, dict]]:
    entries = await redis.xrange(events_key(run_id), min=start, max=end)
    for event_id, fields in entries:
        evt_type = fields.get("type", "message")
        raw_data = fields.get("data", "{}")
        try:
            data = json.loads(raw_data)
        except Exception:
            data = {"raw": raw_data}
        yield event_id, evt_type, data


def _exclusive_start(last_event_id: str | None) -> str:
    """Convert a Last-Event-ID into the `(id` exclusive min for XRANGE."""
    if not last_event_id:
        return "-"
    return f"({last_event_id}"


async def _mark_orphaned(run_id: str) -> None:
    redis = get_redis()
    ttl = get_settings().run_ttl_seconds
    pipe = redis.pipeline()
    pipe.hset(
        meta_key(run_id),
        mapping={"status": RunStatus.ORPHANED, "updated_at": _now_iso()},
    )
    pipe.expire(meta_key(run_id), ttl)
    pipe.expire(events_key(run_id), ttl)
    await pipe.execute()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
