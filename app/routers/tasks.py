from __future__ import annotations

from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import Request
from fastapi.responses import JSONResponse

from app.config import Settings
from app.config import get_settings
from app.repositories import ContestRepository
from app.repositories import get_repository
from app.services.contest import get_event
from app.services.contest import judge_single_submission
from app.services.contest import refresh_balanced_scores
from app.services.judging_jobs import verify_task_token
from app.storage import BaseImageStorage
from app.storage import get_storage


router = APIRouter()


@router.post("/internal/tasks/judging")
async def process_judging_task(
    request: Request,
    repository: ContestRepository = Depends(get_repository),
    storage: BaseImageStorage = Depends(get_storage),
    settings: Settings = Depends(get_settings),
) -> JSONResponse:
    try:
        verify_task_token(request.headers.get("X-Task-Token"), settings)
    except PermissionError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    payload = await request.json()
    job_id = str(payload.get("job_id") or "").strip()
    submission_id = str(payload.get("submission_id") or "").strip()
    if not job_id or not submission_id:
        raise HTTPException(status_code=400, detail="job_id and submission_id are required.")

    job = repository.get_judging_job(job_id)
    if job is None:
        return JSONResponse({"status": "ignored", "reason": "job not found"})
    if job.state in {"completed", "failed"}:
        return JSONResponse({"status": "ignored", "reason": "job already completed"})

    event = get_event(repository, settings)
    success, provider_name, error = judge_single_submission(
        repository,
        storage,
        submission_id=submission_id,
        event=event,
        settings=settings,
        refresh_balancing=False,
    )
    updated = repository.advance_judging_job(
        job_id,
        submission_id=submission_id,
        success=success,
        error=error,
    )
    if updated.state == "completed":
        refresh_balanced_scores(repository)
    return JSONResponse(
        {
            "status": "ok",
            "provider_name": provider_name,
            "job_id": updated.id,
            "state": updated.state,
            "processed_count": updated.processed_count,
            "total_count": updated.total_count,
            "error_count": updated.error_count,
        },
    )
