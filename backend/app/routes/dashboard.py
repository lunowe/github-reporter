# app/routes/dashboard.py
"""
GET /api/dashboard/summary — cached repo summary, no agent involved.
"""

import logging
from urllib.parse import unquote

from fastapi import APIRouter, Depends, HTTPException, Query

from app.auth import get_activated_user
from app.config import get_settings, Settings
from app.services.github_service import GitHubService
from app.services.token_resolver import resolve_github_token
from app.services.dashboard_cache import get_cached_summary, set_cached_summary

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/summary")
async def repo_summary(
    repo: str = Query(..., description="owner/repo"),
    refresh: bool = Query(False, description="Force refresh from GitHub"),
    user: dict = Depends(get_activated_user),
):
    """
    Return repo summary stats.
    Serves from DB cache (5min TTL) unless refresh=true.
    """
    # Try cache first
    if not refresh:
        cached = await get_cached_summary(repo)
        if cached:
            logger.info("Dashboard cache hit for %s", repo)
            return {"source": "cache", "summary": cached}

    # Fetch fresh from GitHub using the user's own OAuth token
    import asyncio
    from concurrent.futures import ThreadPoolExecutor

    token = await resolve_github_token(user)

    logger.info("Dashboard cache miss — fetching %s from GitHub", repo)
    try:
        github_service = GitHubService(token=token, repo_full_name=repo)
        loop = asyncio.get_event_loop()
        executor = ThreadPoolExecutor(max_workers=1)
        summary = await asyncio.wait_for(
            loop.run_in_executor(executor, github_service.get_repo_summary),
            timeout=15,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="GitHub API timeout — bitte erneut versuchen")
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"GitHub API Fehler: {e}")

    # Store in cache
    await set_cached_summary(repo, summary)

    return {"source": "fresh", "summary": summary}


@router.get("/details")
async def repo_details(
    repo: str = Query(..., description="owner/repo"),
    user: dict = Depends(get_activated_user),
):
    """
    Return extended dashboard data: commit activity, languages,
    contributors, recent activity. Each section is fetched independently
    so a single slow/hanging call doesn't block everything.
    """
    import asyncio
    from concurrent.futures import ThreadPoolExecutor

    token = await resolve_github_token(user)

    try:
        github_service = GitHubService(token=token, repo_full_name=repo)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"GitHub API Fehler: {e}")

    loop = asyncio.get_event_loop()
    executor = ThreadPoolExecutor(max_workers=4)

    async def safe_call(fn, timeout=10):
        """Run a blocking GitHub call in a thread with a timeout."""
        try:
            return await asyncio.wait_for(
                loop.run_in_executor(executor, fn),
                timeout=timeout,
            )
        except Exception:
            return None

    # Run all four calls in parallel with individual timeouts
    activity, languages, contributors, recent = await asyncio.gather(
        safe_call(github_service.get_commit_activity, timeout=8),
        safe_call(github_service.get_languages, timeout=8),
        safe_call(github_service.get_top_contributors, timeout=8),
        safe_call(github_service.get_recent_activity, timeout=8),
    )

    return {
        "commit_activity": activity or [],
        "languages": languages or {},
        "contributors": contributors or [],
        "recent_activity": recent or [],
    }
