from __future__ import annotations

from fastapi import APIRouter
from fastapi import Depends
from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.config import Settings
from app.config import get_settings
from app.repositories import ContestRepository
from app.repositories import get_repository
from app.services.contest import effective_score
from app.services.contest import get_event
from app.services.contest import leaderboard
from app.services.contest import podium_comment


router = APIRouter()
templates = Jinja2Templates(directory="app/templates")


@router.get("/presentation", response_class=HTMLResponse)
def presentation(
    request: Request,
    repository: ContestRepository = Depends(get_repository),
    settings: Settings = Depends(get_settings),
) -> HTMLResponse:
    event = get_event(repository, settings)
    winners = leaderboard(repository, limit=3)
    return templates.TemplateResponse(
        "presentation.html",
        {
            "request": request,
            "event": event,
            "winners": winners,
            "effective_score": effective_score,
            "podium_comment": podium_comment,
        },
    )
