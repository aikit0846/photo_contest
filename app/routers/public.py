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
from sqlalchemy.orm import Session

from app.config import Settings
from app.config import get_settings
from app.database import get_db
from app.services.contest import get_event
from app.services.contest import get_guest_by_token
from app.services.contest import invite_url
from app.services.contest import leaderboard
from app.services.contest import save_submission


router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
def home(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> HTMLResponse:
    event = get_event(db, settings)
    top_entries = leaderboard(db, limit=3)
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
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> HTMLResponse:
    event = get_event(db, settings)
    guest = get_guest_by_token(db, token)
    if guest is None:
        raise HTTPException(status_code=404, detail="Invite link not found.")
    return templates.TemplateResponse(
        "join.html",
        {
            "request": request,
            "event": event,
            "guest": guest,
            "invite_url": invite_url(settings, guest),
            "message": request.query_params.get("message"),
            "error": request.query_params.get("error"),
        },
    )


@router.post("/join/{token}")
def submit_photo(
    token: str,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
    caption: str | None = Form(default=None),
    photo: UploadFile = File(...),
) -> RedirectResponse:
    event = get_event(db, settings)
    guest = get_guest_by_token(db, token)
    if guest is None:
        raise HTTPException(status_code=404, detail="Invite link not found.")
    try:
        save_submission(
            db,
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
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> Response:
    guest = get_guest_by_token(db, token)
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
