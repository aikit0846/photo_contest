from __future__ import annotations

import io

import qrcode
import qrcode.image.svg
from fastapi import APIRouter
from fastapi import Cookie
from fastapi import Depends
from fastapi import File
from fastapi import Form
from fastapi import HTTPException
from fastapi import Request
from fastapi import UploadFile
from fastapi.responses import HTMLResponse
from fastapi.responses import RedirectResponse
from fastapi.responses import Response
from fastapi.templating import Jinja2Templates

from app.config import Settings
from app.config import get_settings
from app.repositories import ContestRepository
from app.repositories import get_repository
from app.services.contest import common_entry_url
from app.services.contest import entry_category_label
from app.services.contest import entry_category_options
from app.services.contest import effective_score
from app.services.contest import feedback_comments
from app.services.contest import feedback_display_score
from app.services.contest import feedback_score_ceiling
from app.services.contest import guests_for_category
from app.services.contest import invite_url
from app.services.contest import leaderboard
from app.services.contest import podium_comment
from app.services.contest import podium_comment_lines
from app.services.contest import save_submission
from app.services.contest import score_breakdown
from app.services.contest import short_comment
from app.services.contest import get_event
from app.storage import BaseImageStorage
from app.storage import get_storage


router = APIRouter()
templates = Jinja2Templates(directory="app/templates")
REMEMBERED_GUEST_COOKIE = "remembered_guest_token"


@router.get("/", response_class=HTMLResponse)
def home(
    request: Request,
    repository: ContestRepository = Depends(get_repository),
    settings: Settings = Depends(get_settings),
) -> HTMLResponse:
    event = get_event(repository, settings)
    top_entries = leaderboard(repository, limit=3)
    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "event": event,
            "top_entries": top_entries,
            "short_comment": short_comment,
            "message": request.query_params.get("message"),
        },
    )


@router.get("/join/{token}", response_class=HTMLResponse)
def join_page(
    token: str,
    request: Request,
    repository: ContestRepository = Depends(get_repository),
    settings: Settings = Depends(get_settings),
) -> HTMLResponse:
    event = get_event(repository, settings)
    guest = repository.get_guest_by_token(token)
    if guest is None:
        raise HTTPException(status_code=404, detail="Invite link not found.")
    submission = guest.submission
    feedback_visible = bool(event.feedback_released and submission is not None)
    feedback_ready = bool(
        feedback_visible
        and submission is not None
        and submission.score is not None
        and submission.judging_state == "judged"
    )
    feedback_ceiling = feedback_score_ceiling(repository) if feedback_visible else None
    feedback_score = (
        feedback_display_score(
            submission,
            eligible=guest.eligible,
            ceiling=feedback_ceiling,
        )
        if feedback_ready and submission is not None
        else None
    )
    raw_score = effective_score(submission) if feedback_ready and submission is not None else None
    ranked = leaderboard(repository, limit=3) if feedback_visible else []
    rank_lookup = {item.id: index + 1 for index, item in enumerate(ranked)}
    feedback_rank = rank_lookup.get(submission.id) if submission is not None else None
    feedback_lines = (
        podium_comment_lines(submission, feedback_rank)
        if feedback_ready and submission is not None and feedback_rank is not None
        else feedback_comments(submission) if feedback_ready and submission is not None
        else []
    )
    feedback_breakdown = (
        score_breakdown(submission, target_total=feedback_score)
        if feedback_ready and submission is not None and feedback_score is not None
        else []
    )
    message = request.query_params.get("message")
    error = request.query_params.get("error")
    success_message = "写真を受け付けました。締切までは差し替え可能です。"
    response = templates.TemplateResponse(
        "join.html",
        {
            "request": request,
            "event": event,
            "guest": guest,
            "invite_url": invite_url(settings, guest),
            "config": settings,
            "message": message,
            "error": error,
            "hide_flash": message == success_message and not error,
            "feedback_visible": feedback_visible,
            "feedback_ready": feedback_ready,
            "feedback_score": feedback_score,
            "feedback_raw_score": raw_score,
            "feedback_is_capped": (
                feedback_ready
                and feedback_score is not None
                and raw_score is not None
                and feedback_score < raw_score
            ),
            "feedback_rank": feedback_rank,
            "feedback_lines": [line for line in feedback_lines if line],
            "feedback_breakdown": feedback_breakdown,
        },
    )
    response.set_cookie(
        REMEMBERED_GUEST_COOKIE,
        guest.invite_token,
        max_age=60 * 60 * 24 * 30,
        httponly=False,
        samesite="lax",
    )
    return response


@router.post("/join/{token}")
def submit_photo(
    token: str,
    repository: ContestRepository = Depends(get_repository),
    storage: BaseImageStorage = Depends(get_storage),
    settings: Settings = Depends(get_settings),
    caption: str | None = Form(default=None),
    photo: UploadFile = File(...),
) -> RedirectResponse:
    event = get_event(repository, settings)
    guest = repository.get_guest_by_token(token)
    if guest is None:
        raise HTTPException(status_code=404, detail="Invite link not found.")
    try:
        save_submission(
            repository,
            storage,
            event=event,
            guest=guest,
            upload=photo,
            caption=caption,
            settings=settings,
        )
        return RedirectResponse(
            f"/join/{token}?message=写真を受け付けました。締切までは差し替え可能です。",
            status_code=303,
        )
    except HTTPException as exc:
        return RedirectResponse(
            f"/join/{token}?error={exc.detail}",
            status_code=303,
        )


@router.get("/guests/{token}/qr.svg")
def guest_qr(
    token: str,
    repository: ContestRepository = Depends(get_repository),
    settings: Settings = Depends(get_settings),
) -> Response:
    guest = repository.get_guest_by_token(token)
    if guest is None:
        raise HTTPException(status_code=404, detail="Invite link not found.")

    qr = qrcode.QRCode(
        border=1,
        box_size=8,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        image_factory=qrcode.image.svg.SvgPathImage,
    )
    qr.add_data(invite_url(settings, guest))
    qr.make(fit=True)
    image = qr.make_image()
    buffer = io.BytesIO()
    image.save(buffer)
    return Response(content=buffer.getvalue(), media_type="image/svg+xml")


@router.get("/entry", response_class=HTMLResponse)
def entry_home(
    request: Request,
    remembered_guest_token: str | None = Cookie(default=None, alias=REMEMBERED_GUEST_COOKIE),
    repository: ContestRepository = Depends(get_repository),
    settings: Settings = Depends(get_settings),
) -> HTMLResponse:
    event = get_event(repository, settings)
    remembered_guest = (
        repository.get_guest_by_token(remembered_guest_token) if remembered_guest_token else None
    )
    return templates.TemplateResponse(
        "entry_home.html",
        {
            "request": request,
            "event": event,
            "remembered_guest": remembered_guest,
            "categories": entry_category_options(),
            "message": request.query_params.get("message"),
            "error": request.query_params.get("error"),
        },
    )


@router.get("/entry/reset")
def reset_entry() -> RedirectResponse:
    response = RedirectResponse("/entry?message=別の参加者として選び直せます。", status_code=303)
    response.delete_cookie(REMEMBERED_GUEST_COOKIE)
    return response


@router.get("/entry/qr.svg")
def common_entry_qr(settings: Settings = Depends(get_settings)) -> Response:
    qr = qrcode.QRCode(
        border=1,
        box_size=8,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        image_factory=qrcode.image.svg.SvgPathImage,
    )
    qr.add_data(common_entry_url(settings))
    qr.make(fit=True)
    image = qr.make_image()
    buffer = io.BytesIO()
    image.save(buffer)
    return Response(content=buffer.getvalue(), media_type="image/svg+xml")


@router.get("/entry/category/{category_key}", response_class=HTMLResponse)
def entry_category(
    category_key: str,
    request: Request,
    repository: ContestRepository = Depends(get_repository),
    settings: Settings = Depends(get_settings),
) -> HTMLResponse:
    categories = {option["key"] for option in entry_category_options()}
    if category_key not in categories:
        raise HTTPException(status_code=404, detail="Category not found.")
    event = get_event(repository, settings)
    guests = guests_for_category(repository, category_key)
    return templates.TemplateResponse(
        "entry_category.html",
        {
            "request": request,
            "event": event,
            "category_key": category_key,
            "category_label": entry_category_label(category_key),
            "guests": guests,
        },
    )


@router.post("/entry/select/{guest_id}")
def select_entry_guest(
    guest_id: str,
    repository: ContestRepository = Depends(get_repository),
) -> RedirectResponse:
    guest = repository.get_guest_by_id(guest_id)
    if guest is None:
        raise HTTPException(status_code=404, detail="Guest not found.")
    response = RedirectResponse(f"/join/{guest.invite_token}", status_code=303)
    response.set_cookie(
        REMEMBERED_GUEST_COOKIE,
        guest.invite_token,
        max_age=60 * 60 * 24 * 30,
        httponly=False,
        samesite="lax",
    )
    return response


@router.get("/submissions/{submission_id}/image")
def submission_image(
    submission_id: str,
    repository: ContestRepository = Depends(get_repository),
    storage: BaseImageStorage = Depends(get_storage),
) -> Response:
    submission = repository.get_submission(submission_id)
    if submission is None:
        raise HTTPException(status_code=404, detail="Submission not found.")
    image_bytes = storage.read_image(submission.storage_key)
    return Response(
        content=image_bytes,
        media_type=submission.mime_type,
        headers={"Cache-Control": "public, max-age=3600"},
    )
