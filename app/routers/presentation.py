from __future__ import annotations

from fastapi import APIRouter
from fastapi import Depends
from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.config import Settings
from app.config import get_settings
from app.database import get_db
from app.services.contest import effective_score
from app.services.contest import get_event
from app.services.contest import leaderboard


router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/presentation", response_class=HTMLResponse)
def presentation(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> HTMLResponse:
    event = get_event(db, settings)
    winners = leaderboard(db, limit=3)
    return templates.TemplateResponse(
        "presentation.html",
        {
            "request": request,
            "event": event,
            "winners": winners,
            "effective_score": effective_score,
        },
    )
