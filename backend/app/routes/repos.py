# app/routes/repos.py
"""
GET/POST/DELETE /api/repos — manage connected GitHub repositories (MongoDB-backed).
GET /api/repos/available — list GitHub repos accessible to the authenticated user.
"""

import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException
from github import Github, Auth

from app.auth import get_current_user
from app.config import Settings, get_settings
from app.db import get_db
from app.models.api import RepoConnection, RepoConnectionOut
from app.services.token_resolver import resolve_github_token

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["repos"])


@router.get("/repos", response_model=list[RepoConnectionOut])
async def list_repos(
    user: dict = Depends(get_current_user),
):
    db = get_db()
    repos = []
    async for doc in db.repos.find({"user_id": str(user["_id"])}):
        repos.append({
            "id": doc.get("repo_id", str(doc["_id"])),
            "repo_full_name": doc["repo_full_name"],
            "display_name": doc.get("display_name", doc["repo_full_name"].split("/")[-1]),
            "default_branch": doc.get("default_branch", "main"),
        })

    return repos


@router.post("/repos", response_model=RepoConnectionOut)
async def add_repo(
    body: RepoConnection,
    user: dict = Depends(get_current_user),
):
    db = get_db()
    user_id = str(user["_id"])

    existing = await db.repos.find_one({
        "user_id": user_id,
        "repo_full_name": body.repo_full_name,
    })
    if existing:
        raise HTTPException(status_code=409, detail="Repository bereits verbunden.")

    repo_id = str(uuid.uuid4())[:8]
    doc = {
        "repo_id": repo_id,
        "user_id": user_id,
        "repo_full_name": body.repo_full_name,
        "display_name": body.display_name or body.repo_full_name.split("/")[-1],
        "default_branch": body.default_branch,
    }
    await db.repos.insert_one(doc)

    return {
        "id": repo_id,
        "repo_full_name": doc["repo_full_name"],
        "display_name": doc["display_name"],
        "default_branch": doc["default_branch"],
    }


@router.get("/repos/available")
async def available_repos(
    user: dict = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
):
    """
    List GitHub repositories accessible to the authenticated user.
    With GitHub Apps, the user token only sees repos where the app is installed.
    Returns { repos, install_url, installed }.
    """
    token = await resolve_github_token(user)
    install_url = (
        f"https://github.com/apps/{settings.github_app_slug}/installations/new"
        if settings.github_app_slug
        else ""
    )

    try:
        gh = Github(auth=Auth.Token(token))
        gh_user = gh.get_user()

        # get_repos() with a GitHub App user token returns only repos
        # where the app is installed. If the app isn't installed anywhere,
        # this returns an empty list.
        repos = []
        for repo in gh_user.get_repos(sort="updated", direction="desc"):
            repos.append({
                "full_name": repo.full_name,
                "name": repo.name,
                "description": repo.description or "",
                "private": repo.private,
                "default_branch": repo.default_branch or "main",
                "owner": repo.owner.login,
                "updated_at": repo.updated_at.isoformat() if repo.updated_at else "",
            })
            if len(repos) >= 100:
                break

        return {
            "repos": repos,
            "install_url": install_url,
            "installed": len(repos) > 0,
        }

    except Exception as e:
        logger.error("Failed to fetch available repos: %s", e)
        raise HTTPException(status_code=502, detail=f"GitHub API Fehler: {e}")


@router.delete("/repos/{repo_id}")
async def delete_repo(
    repo_id: str,
    user: dict = Depends(get_current_user),
):
    db = get_db()
    result = await db.repos.delete_one({
        "repo_id": repo_id,
        "user_id": str(user["_id"]),
    })
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Repository nicht gefunden.")
    return {"status": "deleted"}
