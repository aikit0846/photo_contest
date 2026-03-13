from __future__ import annotations

import io

import qrcode
import qrcode.image.svg
from fastapi import APIRouter
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
from app.services.contest import invite_url
from app.services.contest import leaderboard
from app.services.contest import save_submission
from app.services.contest import get_event
from app.storage import BaseImageStorage
from app.storage import get_storage


router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


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
    return templates.TemplateResponse(
        "join.html",
        {
            "request": request,
            "event": event,
            "guest": guest,
            "invite_url": invite_url(settings, guest),
            "config": settings,
            "message": request.query_params.get("message"),
            "error": request.query_params.get("error"),
        },
    )


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
