from __future__ import annotations

from fastapi import APIRouter
from fastapi import Depends
from fastapi import Form
from fastapi import HTTPException
from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

from app.auth import require_admin
from app.config import Settings
from app.config import get_settings
from app.repositories import ContestRepository
from app.repositories import get_repository
from app.services.contest import common_entry_url
from app.services.contest import create_guest
from app.services.contest import effective_score
from app.services.contest import event_stats
from app.services.contest import get_event
from app.services.contest import judge_submissions
from app.services.contest import leaderboard
from app.services.contest import provider_choices
from app.services.contest import provider_status
from app.storage import BaseImageStorage
from app.storage import get_storage


router = APIRouter(prefix="/admin", dependencies=[Depends(require_admin)])
templates = Jinja2Templates(directory="app/templates")


@router.get("", response_class=HTMLResponse)
def dashboard(
    request: Request,
    repository: ContestRepository = Depends(get_repository),
    settings: Settings = Depends(get_settings),
) -> HTMLResponse:
    event = get_event(repository, settings)
    submissions = repository.list_submissions()
    top_entries = leaderboard(repository, limit=10)
    return templates.TemplateResponse(
        "admin_operations.html",
        {
            "request": request,
            "event": event,
            "submissions": submissions,
            "top_entries": top_entries,
            "stats": event_stats(repository),
            "provider_choices": provider_choices(),
            "provider_status": provider_status(settings),
            "effective_score": effective_score,
            "admin_section": "operations",
            "message": request.query_params.get("message"),
            "error": request.query_params.get("error"),
        },
    )


@router.get("/guests", response_class=HTMLResponse)
def guests_page(
    request: Request,
    repository: ContestRepository = Depends(get_repository),
    settings: Settings = Depends(get_settings),
) -> HTMLResponse:
    event = get_event(repository, settings)
    guests = repository.list_guests()
    return templates.TemplateResponse(
        "admin_guests.html",
        {
            "request": request,
            "event": event,
            "guests": guests,
            "common_entry_url": common_entry_url(settings),
            "admin_section": "guests",
            "message": request.query_params.get("message"),
            "error": request.query_params.get("error"),
        },
    )


@router.get("/guests/{guest_id}", response_class=HTMLResponse)
def edit_guest_page(
    guest_id: str,
    request: Request,
    repository: ContestRepository = Depends(get_repository),
    settings: Settings = Depends(get_settings),
) -> HTMLResponse:
    event = get_event(repository, settings)
    guest = repository.get_guest_by_id(guest_id)
    if guest is None:
        raise HTTPException(status_code=404, detail="Guest not found.")
    return templates.TemplateResponse(
        "admin_guest_edit.html",
        {
            "request": request,
            "event": event,
            "guest": guest,
            "admin_section": "guests",
            "message": request.query_params.get("message"),
            "error": request.query_params.get("error"),
        },
    )


@router.post("/event/toggle")
def toggle_event(
    repository: ContestRepository = Depends(get_repository),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    event = get_event(repository, settings)
    updated = repository.update_event(submissions_open=not event.submissions_open)
    state = "再開" if updated.submissions_open else "締切"
    return RedirectResponse(f"/admin?message=投稿受付を{state}にしました。", status_code=303)


@router.post("/event/provider")
def update_provider(
    provider_preference: str = Form(...),
    model_hint: str | None = Form(default=None),
    repository: ContestRepository = Depends(get_repository),
) -> RedirectResponse:
    if provider_preference not in provider_choices():
        raise HTTPException(status_code=400, detail="Unknown provider.")
    repository.update_event(
        provider_preference=provider_preference,
        model_hint=(model_hint or "").strip() or None,
    )
    return RedirectResponse("/admin?message=AIプロバイダ設定を更新しました。", status_code=303)


@router.post("/guests")
def add_guest(
    name: str = Form(...),
    display_name: str | None = Form(default=None),
    side: str = Form(default="groom"),
    table_name: str | None = Form(default=None),
    group_type: str = Form(default="friend"),
    eligible: str | None = Form(default=None),
    notes: str | None = Form(default=None),
    repository: ContestRepository = Depends(get_repository),
) -> RedirectResponse:
    create_guest(
        repository,
        name=name,
        display_name=display_name,
        side=side,
        table_name=table_name,
        group_type=group_type,
        eligible=eligible == "on",
        notes=notes,
    )
    return RedirectResponse("/admin/guests?message=ゲストを追加しました。", status_code=303)


@router.post("/guests/{guest_id}/eligibility")
def toggle_guest_eligibility(
    guest_id: str,
    repository: ContestRepository = Depends(get_repository),
) -> RedirectResponse:
    guest = repository.get_guest_by_id(guest_id)
    if guest is None:
        raise HTTPException(status_code=404, detail="Guest not found.")
    updated = repository.set_guest_eligibility(guest_id, not guest.eligible)
    state = "抽選対象" if updated.eligible else "対象外"
    return RedirectResponse(f"/admin/guests?message={guest.label} を{state}にしました。", status_code=303)


@router.post("/guests/{guest_id}/update")
def update_guest(
    guest_id: str,
    name: str = Form(...),
    display_name: str | None = Form(default=None),
    side: str = Form(default="groom"),
    table_name: str | None = Form(default=None),
    group_type: str = Form(default="friend"),
    eligible: str | None = Form(default=None),
    notes: str | None = Form(default=None),
    repository: ContestRepository = Depends(get_repository),
) -> RedirectResponse:
    guest = repository.get_guest_by_id(guest_id)
    if guest is None:
        raise HTTPException(status_code=404, detail="Guest not found.")
    repository.update_guest(
        guest_id,
        name=name,
        display_name=display_name,
        side=side,
        table_name=table_name,
        group_type=group_type,
        eligible=eligible == "on",
        notes=notes,
    )
    return RedirectResponse(f"/admin/guests?message={guest.label} を更新しました。", status_code=303)


@router.post("/guests/{guest_id}/delete")
def delete_guest(
    guest_id: str,
    repository: ContestRepository = Depends(get_repository),
    storage: BaseImageStorage = Depends(get_storage),
) -> RedirectResponse:
    guest = repository.get_guest_by_id(guest_id)
    if guest is None:
        raise HTTPException(status_code=404, detail="Guest not found.")
    if guest.submission is not None:
        storage.delete_image(guest.submission.storage_key)
    repository.delete_guest(guest_id)
    return RedirectResponse(f"/admin/guests?message={guest.label} を削除しました。", status_code=303)


@router.post("/submissions/judge")
def run_judging(
    force: str | None = Form(default=None),
    repository: ContestRepository = Depends(get_repository),
    storage: BaseImageStorage = Depends(get_storage),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    event = get_event(repository, settings)
    judged, errors, provider_name = judge_submissions(
        repository,
        storage,
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
    submission_id: str,
    reason: str | None = Form(default=None),
    repository: ContestRepository = Depends(get_repository),
) -> RedirectResponse:
    submission = repository.get_submission(submission_id)
    if submission is None:
        raise HTTPException(status_code=404, detail="Submission not found.")
    repository.set_submission_exclusion(
        submission_id,
        is_excluded=True,
        reason=(reason or "").strip() or "Admin excluded",
    )
    return RedirectResponse("/admin?message=投稿をランキング対象外にしました。", status_code=303)


@router.post("/submissions/{submission_id}/restore")
def restore_submission(
    submission_id: str,
    repository: ContestRepository = Depends(get_repository),
) -> RedirectResponse:
    submission = repository.get_submission(submission_id)
    if submission is None:
        raise HTTPException(status_code=404, detail="Submission not found.")
    repository.set_submission_exclusion(submission_id, is_excluded=False, reason=None)
    return RedirectResponse("/admin?message=投稿をランキング対象に戻しました。", status_code=303)


@router.post("/submissions/{submission_id}/rank")
def update_submission_rank(
    submission_id: str,
    display_order: str | None = Form(default=None),
    admin_score_adjustment: str | None = Form(default=None),
    repository: ContestRepository = Depends(get_repository),
) -> RedirectResponse:
    submission = repository.get_submission(submission_id)
    if submission is None:
        raise HTTPException(status_code=404, detail="Submission not found.")
    display_value = (display_order or "").strip()
    adjustment_value = (admin_score_adjustment or "").strip()
    repository.update_submission_rank(
        submission_id,
        display_order=int(display_value) if display_value else None,
        admin_score_adjustment=float(adjustment_value) if adjustment_value else 0.0,
    )
    return RedirectResponse("/admin?message=手動調整を保存しました。", status_code=303)
