from __future__ import annotations

from fastapi import APIRouter
from fastapi import Depends
from fastapi import Form
from fastapi import HTTPException
from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import require_admin
from app.config import Settings
from app.config import get_settings
from app.database import get_db
from app.models import Guest
from app.models import Submission
from app.services.contest import create_guest
from app.services.contest import effective_score
from app.services.contest import event_stats
from app.services.contest import get_event
from app.services.contest import guest_query
from app.services.contest import invite_url
from app.services.contest import judge_submissions
from app.services.contest import leaderboard
from app.services.contest import provider_choices
from app.services.contest import provider_status
from app.services.contest import submission_query


router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])
templates = Jinja2Templates(directory="app/templates")


@router.get("", response_class=HTMLResponse)
def dashboard(
    request: Request,
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> HTMLResponse:
    event = get_event(db, settings)
    guests = db.scalars(guest_query()).all()
    submissions = db.scalars(submission_query()).all()
    top_entries = leaderboard(db, limit=10)
    return templates.TemplateResponse(
        "admin.html",
        {
            "request": request,
            "event": event,
            "guests": guests,
            "submissions": submissions,
            "top_entries": top_entries,
            "invite_url": lambda guest: invite_url(settings, guest),
            "stats": event_stats(db),
            "provider_choices": provider_choices(),
            "provider_status": provider_status(settings),
            "effective_score": effective_score,
            "message": request.query_params.get("message"),
            "error": request.query_params.get("error"),
        },
    )


@router.post("/event/toggle")
def toggle_event(
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    event = get_event(db, settings)
    event.submissions_open = not event.submissions_open
    db.commit()
    state = "再開" if event.submissions_open else "締切"
    return RedirectResponse(f"/admin?message=投稿受付を{state}にしました。", status_code=303)


@router.post("/event/provider")
def update_provider(
    provider_preference: str = Form(...),
    model_hint: str | None = Form(default=None),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    event = get_event(db, settings)
    if provider_preference not in provider_choices():
        raise HTTPException(status_code=400, detail="Unknown provider.")
    event.provider_preference = provider_preference
    event.model_hint = (model_hint or "").strip() or None
    db.commit()
    return RedirectResponse("/admin?message=AIプロバイダ設定を更新しました。", status_code=303)


@router.post("/guests")
def add_guest(
    name: str = Form(...),
    display_name: str | None = Form(default=None),
    table_name: str | None = Form(default=None),
    group_type: str = Form(default="friend"),
    eligible: str | None = Form(default=None),
    notes: str | None = Form(default=None),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    create_guest(
        db,
        name=name,
        display_name=display_name,
        table_name=table_name,
        group_type=group_type,
        eligible=eligible == "on",
        notes=notes,
    )
    return RedirectResponse("/admin?message=ゲストを追加しました。", status_code=303)


@router.post("/guests/{guest_id}/eligibility")
def toggle_guest_eligibility(
    guest_id: int,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    guest = db.get(Guest, guest_id)
    if guest is None:
        raise HTTPException(status_code=404, detail="Guest not found.")
    guest.eligible = not guest.eligible
    db.commit()
    state = "抽選対象" if guest.eligible else "対象外"
    return RedirectResponse(f"/admin?message={guest.label} を{state}にしました。", status_code=303)


@router.post("/submissions/judge")
def run_judging(
    force: str | None = Form(default=None),
    db: Session = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    event = get_event(db, settings)
    judged, errors, provider_name = judge_submissions(
        db,
        event=event,
        settings=settings,
        force=force == "on",
    )
    if errors:
        message = f"{judged}件を採点し、{len(errors)}件でエラーがありました。({provider_name})"
        return RedirectResponse(f"/admin?error={message}", status_code=303)
    return RedirectResponse(
        f"/admin?message={judged}件を採点しました。({provider_name})",
        status_code=303,
    )


@router.post("/submissions/{submission_id}/exclude")
def exclude_submission(
    submission_id: int,
    reason: str | None = Form(default=None),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    submission = db.get(Submission, submission_id)
    if submission is None:
        raise HTTPException(status_code=404, detail="Submission not found.")
    submission.is_excluded = True
    submission.excluded_reason = (reason or "").strip() or "Admin excluded"
    submission.display_order = None
    db.commit()
    return RedirectResponse("/admin?message=投稿をランキング対象外にしました。", status_code=303)


@router.post("/submissions/{submission_id}/restore")
def restore_submission(
    submission_id: int,
    db: Session = Depends(get_db),
) -> RedirectResponse:
    submission = db.get(Submission, submission_id)
    if submission is None:
        raise HTTPException(status_code=404, detail="Submission not found.")
    submission.is_excluded = False
    submission.excluded_reason = None
    db.commit()
    return RedirectResponse("/admin?message=投稿をランキング対象に戻しました。", status_code=303)


@router.post("/submissions/{submission_id}/rank")
def update_submission_rank(
    submission_id: int,
    display_order: str | None = Form(default=None),
    admin_score_adjustment: str | None = Form(default=None),
    db: Session = Depends(get_db),
) -> RedirectResponse:
    submission = db.get(Submission, submission_id)
    if submission is None:
        raise HTTPException(status_code=404, detail="Submission not found.")
    display_value = (display_order or "").strip()
    adjustment_value = (admin_score_adjustment or "").strip()
    submission.display_order = int(display_value) if display_value else None
    submission.admin_score_adjustment = float(adjustment_value) if adjustment_value else 0.0
    db.commit()
    return RedirectResponse("/admin?message=手動調整を保存しました。", status_code=303)
