"""Authentication endpoints (AUTH-01).

Tokens travel by email and cookie, never in a response body: an invitation or recovery link proves
control of the mailbox, which is the out-of-band channel the requirement asks for.
"""

from __future__ import annotations

from fastapi import APIRouter, Response, status

from app.api.deps import ContextDep, SessionDep, SettingsDep, clear_session_cookie, set_session_cookie
from app.identity import service
from app.identity.schemas import (
    AcceptInvitationIn,
    LoginIn,
    PasswordResetConfirmIn,
    PasswordResetRequestIn,
    UserOut,
)

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", summary="Sign in and start a session")
async def login(
    payload: LoginIn, response: Response, session: SessionDep, settings: SettingsDep
) -> UserOut:
    signed_in = await service.login(session, email=payload.email, password=payload.password)
    set_session_cookie(response, signed_in.token, settings)
    return signed_in.user


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT, summary="End the session")
async def logout(
    request_context: ContextDep,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
) -> None:
    await service.logout_session(session, session_id=request_context.session_id)
    clear_session_cookie(response, settings)


@router.get("/me", summary="The signed-in user")
async def me(request_context: ContextDep) -> UserOut:
    return request_context.user


@router.post("/accept-invitation", summary="Set a password and activate an invited account")
async def accept_invitation(
    payload: AcceptInvitationIn,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
) -> UserOut:
    user = await service.accept_invitation(
        session,
        token=payload.token,
        password=payload.password,
        display_name=payload.display_name,
    )
    # Accepting proves control of the invited mailbox, so the session starts here.
    signed_in = await service.start_session(session, user_id=user.id)
    set_session_cookie(response, signed_in.token, settings)
    return user


@router.post(
    "/password-reset",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Request a recovery link",
)
async def request_password_reset(
    payload: PasswordResetRequestIn, session: SessionDep
) -> dict[str, str]:
    await service.request_password_reset(session, email=payload.email)
    # Identical for a known and an unknown address: the answer must not enumerate accounts.
    return {"status": "accepted"}


@router.post(
    "/password-reset/confirm",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Set a new password with a recovery token",
)
async def confirm_password_reset(payload: PasswordResetConfirmIn, session: SessionDep) -> None:
    await service.reset_password(session, token=payload.token, password=payload.password)
