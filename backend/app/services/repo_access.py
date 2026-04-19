# app/services/repo_access.py
"""
Repo authorization helpers shared by repo-scoped endpoints.
"""

from app.db import get_db


async def get_authorized_repo(user: dict, repo_full_name: str) -> dict | None:
    """
    Return the connected repo document if the user may access it.

    GitHub users may access only their own connected repos.
    Viewer/email users may access only repos explicitly granted via invite.
    """
    db = get_db()

    if user.get("auth_method") == "email":
        allowed_ids = user.get("allowed_repo_ids", [])
        proxy_user_id = user.get("proxy_github_user_id", "")
        if not allowed_ids or not proxy_user_id:
            return None
        query = {
            "user_id": proxy_user_id,
            "repo_id": {"$in": allowed_ids},
            "repo_full_name": repo_full_name,
        }
    else:
        query = {
            "user_id": str(user["_id"]),
            "repo_full_name": repo_full_name,
        }

    return await db.repos.find_one(query)
