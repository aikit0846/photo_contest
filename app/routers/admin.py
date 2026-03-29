from __future__ import annotations

from fastapi import APIRouter
from fastapi import Depends
from fastapi import Form
from fastapi import HTTPException
from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.responses import JSONResponse
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
from app.services.contest import feedback_lines_for_submission
from app.services.contest import get_event
from app.services.contest import judge_submission_batch
from app.services.contest import judge_submissions
from app.services.contest import leaderboard
from app.services.contest import plan_judging_run
from app.services.contest import podium_comment
from app.services.contest import refresh_balanced_scores
from app.services.contest import provider_choices
from app.services.contest import provider_status
from app.services.contest import short_comment
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
    ranking_submissions = [
        submission
        for submission in submissions
        if submission.guest is not None and submission.guest.eligible and not submission.is_excluded
    ]
    non_ranking_submissions = [
        submission
        for submission in submissions
        if submission.guest is None or not submission.guest.eligible or submission.is_excluded
    ]
    top_entries = leaderboard(repository, limit=10)
    feedback_rank_lookup = {
        item.id: index + 1
        for index, item in enumerate(leaderboard(repository, limit=3))
    }
    return templates.TemplateResponse(
        "admin_operations.html",
        {
            "request": request,
            "event": event,
            "submissions": submissions,
            "ranking_submissions": ranking_submissions,
            "non_ranking_submissions": non_ranking_submissions,
            "top_entries": top_entries,
            "stats": event_stats(repository),
            "provider_choices": provider_choices(),
            "provider_status": provider_status(settings),
            "effective_score": effective_score,
            "feedback_lines_for_submission": feedback_lines_for_submission,
            "feedback_rank_lookup": feedback_rank_lookup,
            "podium_comment": podium_comment,
            "short_comment": short_comment,
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
    updated = repository.update_event(
        submissions_open=not event.submissions_open,
        feedback_released=False,
    )
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


@router.post("/event/feedback/release")
def release_feedback(
    redirect_to: str | None = Form(default=None),
    repository: ContestRepository = Depends(get_repository),
    settings: Settings = Depends(get_settings),
) -> RedirectResponse:
    event = get_event(repository, settings)
    target = redirect_to or "/admin"
    separator = "&" if "?" in target else "?"
    if event.submissions_open:
        return RedirectResponse(
            f"{target}{separator}error=投稿受付中はゲスト向けフィードバックを公開できません。",
            status_code=303,
        )
    repository.update_event(feedback_released=True)
    return RedirectResponse(
        f"{target}{separator}message=ゲスト向けフィードバックを公開しました。",
        status_code=303,
    )


@router.post("/event/feedback/hide")
def hide_feedback(
    redirect_to: str | None = Form(default=None),
    repository: ContestRepository = Depends(get_repository),
) -> RedirectResponse:
    repository.update_event(feedback_released=False)
    target = redirect_to or "/admin"
    separator = "&" if "?" in target else "?"
    return RedirectResponse(
        f"{target}{separator}message=ゲスト向けフィードバックを非公開に戻しました。",
        status_code=303,
    )


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
    refresh_balanced_scores(repository)
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
    refresh_balanced_scores(repository)
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
    refresh_balanced_scores(repository)
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


@router.post("/submissions/judge/plan")
async def plan_judging(
    request: Request,
    repository: ContestRepository = Depends(get_repository),
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    payload = await request.json()
    event = get_event(repository, settings)
    plan = plan_judging_run(
        repository,
        event=event,
        settings=settings,
        force=bool(payload.get("force")),
    )
    return JSONResponse(plan)


@router.post("/submissions/judge/batch")
async def run_judging_batch(
    request: Request,
    repository: ContestRepository = Depends(get_repository),
    storage: BaseImageStorage = Depends(get_storage),
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    payload = await request.json()
    submission_ids = [str(item) for item in payload.get("submission_ids", []) if str(item).strip()]
    event = get_event(repository, settings)
    judged, errors, provider_name, processed = judge_submission_batch(
        repository,
        storage,
        event=event,
        settings=settings,
        submission_ids=submission_ids,
    )
    return JSONResponse(
        {
            "processed": processed,
            "judged": judged,
            "error_count": len(errors),
            "errors": errors,
            "provider_name": provider_name,
        },
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
    refresh_balanced_scores(repository)
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
    refresh_balanced_scores(repository)
    return RedirectResponse("/admin?message=投稿をランキング対象に戻しました。", status_code=303)


@router.post("/submissions/{submission_id}/adjust")
def update_submission_adjustment(
    submission_id: str,
    admin_score_adjustment: str | None = Form(default=None),
    repository: ContestRepository = Depends(get_repository),
) -> RedirectResponse:
    submission = repository.get_submission(submission_id)
    if submission is None:
        raise HTTPException(status_code=404, detail="Submission not found.")
    adjustment_value = (admin_score_adjustment or "").strip()
    repository.update_submission_adjustment(
        submission_id,
        admin_score_adjustment=float(adjustment_value) if adjustment_value else 0.0,
    )
    refresh_balanced_scores(repository)
    return RedirectResponse("/admin?message=点数補正を保存しました。", status_code=303)
