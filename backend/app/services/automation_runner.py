# app/services/automation_runner.py
"""
Automation execution — runs a chain of prompts against GitHub repos.
Called both by the scheduler (cron-triggered) and by manual "run now" requests.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from datetime import datetime, timezone
from typing import Optional

from app.config import get_settings
from app.services import automations_store, email_service
from app.services.agent_runner import AgentRunner
from app.services.github_service import GitHubService
from app.services.llm_factory import LLMConfig, infer_provider
from app.services.token_resolver import resolve_github_token
from app.services.user_service import get_user_by_id

logger = logging.getLogger(__name__)

# Match {{step1.output}}, {{ step2.output }}, {{stepN.output}} — 1-indexed
_STEP_REF_RE = re.compile(r"\{\{\s*step(\d+)\.output\s*\}\}")


def _substitute_step_refs(prompt: str, prior_outputs: list[str]) -> str:
    """
    Replace {{stepN.output}} references in `prompt` with the corresponding
    output from `prior_outputs` (1-indexed). Unresolved references are left
    as-is so failures are visible rather than silent.
    """
    def _repl(m: re.Match) -> str:
        idx = int(m.group(1)) - 1
        if 0 <= idx < len(prior_outputs):
            return prior_outputs[idx]
        return m.group(0)

    return _STEP_REF_RE.sub(_repl, prompt)


def _compose_final_output(
    *,
    fmt: str,
    template: Optional[str],
    step_results: list[dict],
    prior_outputs: list[str],
) -> str:
    """
    Produce the run's final_output from the config.

    - "last_step": last step's output (legacy/default)
    - "merge": concatenate every step's output with a markdown header
    - "template": render `template` with {{stepN.output}} substitution
      (pure string replacement — no LLM call)
    """
    if fmt == "merge":
        parts: list[str] = []
        for sr in step_results:
            body = sr.get("output") or ""
            if not body.strip():
                continue
            parts.append(f"## {sr['name']}\n\n{body.rstrip()}")
        return "\n\n---\n\n".join(parts)

    if fmt == "template":
        tpl = (template or "").strip()
        if not tpl:
            # Template format selected but no template provided — fall back
            # to merge so the user still gets something useful.
            return _compose_final_output(
                fmt="merge",
                template=None,
                step_results=step_results,
                prior_outputs=prior_outputs,
            )
        return _substitute_step_refs(tpl, prior_outputs)

    # "last_step" and any unknown value
    return prior_outputs[-1] if prior_outputs else ""


async def _run_single_step(
    *,
    user: dict,
    prompt: str,
    repo: str,
    model: str,
) -> str:
    """Build a fresh agent per step (repo varies) and run it once."""
    provider = infer_provider(model)
    llm_config = LLMConfig(provider=provider, model=model, temperature=1)

    token = await resolve_github_token(user)
    github_service = GitHubService(token=token, repo_full_name=repo)

    runner = AgentRunner(llm_config=llm_config, github_service=github_service)
    return await runner.run_once(query=prompt)


async def execute_automation(
    automation: dict,
    *,
    trigger: str = "manual",
    run_id: Optional[str] = None,
) -> dict:
    """
    Execute an automation and persist a run record.

    `automation` is a full automation DB doc (includes user_id + steps).
    `run_id` can be provided if the caller already created a run doc
    (e.g. so the UI can show "queued" immediately); otherwise one is created.
    Returns the final run doc.
    """
    user_id = automation["user_id"]
    automation_id = automation["automation_id"]
    automation_name = automation.get("name", "")
    settings = get_settings()

    # Ensure we have a run doc
    if run_id:
        run = await automations_store.update_run(
            run_id,
            {"status": "running", "started_at": datetime.now(timezone.utc)},
        )
    else:
        run = await automations_store.create_run(
            automation_id=automation_id,
            user_id=user_id,
            automation_name=automation_name,
            trigger=trigger,
        )
    run_id = run["run_id"]

    # Resolve user — needed for GitHub token
    user = await get_user_by_id(user_id)
    if not user:
        err = "Benutzer nicht gefunden — Automation kann nicht ausgeführt werden."
        await automations_store.update_run(run_id, {
            "status": "failed",
            "error": err,
            "completed_at": datetime.now(timezone.utc),
        })
        logger.error("Automation %s: user %s missing", automation_id, user_id)
        return await automations_store.get_run(run_id, user_id) or {}

    default_model = automation.get("model") or settings.default_llm_model
    steps = automation.get("steps", [])
    prior_outputs: list[str] = []
    step_results: list[dict] = []
    failed = False
    error_msg: Optional[str] = None

    for order, step in enumerate(steps, start=1):
        name = step.get("name", f"Schritt {order}")
        raw_prompt = step.get("prompt", "")
        repo = step.get("repo", "")
        model = step.get("model") or default_model

        resolved_prompt = _substitute_step_refs(raw_prompt, prior_outputs)

        logger.info(
            "Automation %s step %d (%s) on repo=%s model=%s",
            automation_id, order, name, repo, model,
        )

        step_result = {
            "order": order,
            "name": name,
            "prompt": resolved_prompt,
            "repo": repo,
            "output": "",
            "duration_ms": 0,
            "error": None,
        }

        t0 = time.perf_counter()
        try:
            output = await _run_single_step(
                user=user,
                prompt=resolved_prompt,
                repo=repo,
                model=model,
            )
            step_result["output"] = output
            prior_outputs.append(output)
        except Exception as e:
            logger.exception("Automation %s step %d failed", automation_id, order)
            step_result["error"] = str(e)
            prior_outputs.append("")  # keep positional indexing for later refs
            failed = True
            error_msg = f"Schritt {order} ({name}) fehlgeschlagen: {e}"
        finally:
            step_result["duration_ms"] = int((time.perf_counter() - t0) * 1000)
            step_results.append(step_result)
            await automations_store.append_step_result(run_id, step_result)

        if failed:
            break  # stop the chain on first failure

    completed_at = datetime.now(timezone.utc)
    final_output = (
        _compose_final_output(
            fmt=automation.get("final_output_format") or "last_step",
            template=automation.get("final_output_template"),
            step_results=step_results,
            prior_outputs=prior_outputs,
        )
        if not failed
        else ""
    )

    final_updates = {
        "status": "failed" if failed else "completed",
        "error": error_msg,
        "final_output": final_output,
        "completed_at": completed_at,
    }
    await automations_store.update_run(run_id, final_updates)
    await automations_store.set_last_run(automation_id, completed_at)

    # Fire-and-forget email notification
    if automation.get("email_enabled") and not failed:
        try:
            run_doc = await automations_store.get_run(run_id, user_id)
            if run_doc:
                recipient = automation.get("email_to") or user.get("email")
                if recipient:
                    await email_service.send_automation_report(
                        to_email=recipient,
                        automation=automation,
                        run=run_doc,
                    )
                    await automations_store.update_run(run_id, {"email_sent": True})
                else:
                    logger.warning(
                        "Automation %s email enabled but no recipient available",
                        automation_id,
                    )
        except Exception:
            logger.exception("Automation %s email send failed", automation_id)

    return await automations_store.get_run(run_id, user_id) or {}


async def execute_automation_by_id(automation_id: str, trigger: str = "schedule"):
    """Scheduler entrypoint — loads the automation and runs it."""
    automation = await automations_store.get_automation_any(automation_id)
    if not automation:
        logger.warning("Scheduler tried to run missing automation %s", automation_id)
        return
    if not automation.get("enabled", True):
        logger.info("Skipping disabled automation %s", automation_id)
        return
    await execute_automation(automation, trigger=trigger)
