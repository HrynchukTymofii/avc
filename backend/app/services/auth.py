"""Bearer-token auth shared with the Next.js frontend.

The frontend authenticates users with NextAuth and mints a short-lived HS256
JWT for backend calls (frontend route /api/backend-token), signed with the
shared API_JWT_SECRET. Every /api request carries it as `Authorization:
Bearer <token>`; this module verifies it and exposes the caller as AuthUser.

With AUTH_ENABLED=false (the default — local dev and tests) everything runs
as one implicit, pre-approved local user and no header is required.

Approval gate: new accounts have approved=false until flipped in the users
table — they can sign in and browse, but job submission requires approval
(GPU time costs real money; credits don't exist yet).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Annotated

from fastapi import Depends, HTTPException, Request

from app.config import Settings
from app.deps import get_settings_dep


@dataclass(frozen=True)
class AuthUser:
    id: str
    email: str | None = None
    name: str | None = None
    approved: bool = False
    role: str = "user"


# The implicit single user when AUTH_ENABLED=false; also the owner of jobs
# created before accounts existed (Job.user_id defaults to "local").
LOCAL_USER = AuthUser(id="local", approved=True, role="admin")


def decode_token(token: str, secret: str) -> AuthUser:
    """Decode and verify a frontend-minted API token. Raises jwt exceptions."""
    import jwt

    payload = jwt.decode(
        token,
        secret,
        algorithms=["HS256"],
        options={"require": ["exp", "sub"]},
    )
    return AuthUser(
        id=str(payload["sub"]),
        email=payload.get("email"),
        name=payload.get("name"),
        approved=bool(payload.get("approved", False)),
        role=str(payload.get("role", "user")),
    )


async def get_current_user(
    request: Request,
    settings: Annotated[Settings, Depends(get_settings_dep)],
) -> AuthUser:
    if not settings.auth_enabled:
        return LOCAL_USER
    if not settings.api_jwt_secret:
        # Server misconfiguration, not a client error — fail loudly.
        raise HTTPException(
            status_code=500, detail="AUTH_ENABLED is set but API_JWT_SECRET is empty"
        )

    import jwt

    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="Not signed in")
    try:
        return decode_token(token, settings.api_jwt_secret)
    except jwt.PyJWTError:
        raise HTTPException(status_code=401, detail="Invalid or expired session token")


def require_approved(user: AuthUser) -> None:
    """Generation costs GPU time — only approved accounts may submit jobs."""
    if not user.approved:
        raise HTTPException(
            status_code=403,
            detail="Your account is awaiting approval — ask the admin to enable it",
        )


def can_view(user: AuthUser, owner_id: str) -> bool:
    return user.role == "admin" or user.id == owner_id
