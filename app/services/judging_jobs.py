from __future__ import annotations

import base64
import json
import time

import google.auth
from google.auth.transport.requests import AuthorizedSession

from app.config import Settings
from app.domain import JudgingJobRecord
from app.repositories import ContestRepository
from app.services.contest import get_event
from app.services.contest import plan_judging_run


TASK_CREATE_RETRY_SECONDS = (2.0, 5.0)


def cloud_tasks_ready(settings: Settings) -> bool:
    return bool(
        cloud_tasks_project(settings)
        and settings.cloud_tasks_location
        and settings.cloud_tasks_queue
        and settings.cloud_tasks_token
        and settings.app_url
    )


def cloud_tasks_project(settings: Settings) -> str | None:
    return settings.cloud_tasks_project or settings.firestore_project


def start_judging_job(
    repository: ContestRepository,
    *,
    settings: Settings,
    force: bool,
) -> tuple[JudgingJobRecord | None, bool]:
    active = repository.get_active_judging_job()
    if active is not None:
        return active, False
    if not cloud_tasks_ready(settings):
        raise RuntimeError("Cloud Tasks is not configured.")

    event = get_event(repository, settings)
    plan = plan_judging_run(repository, event=event, settings=settings, force=force)
    submission_ids = [str(item) for item in plan["submission_ids"]]
    if not submission_ids:
        return None, True

    job = repository.create_judging_job(
        provider_name=str(plan["provider_name"]),
        total_count=len(submission_ids),
    )
    try:
        for submission_id in submission_ids:
            enqueue_judging_task(
                settings,
                job_id=job.id,
                submission_id=submission_id,
            )
        job = repository.mark_judging_job_running(job.id, total_count=len(submission_ids))
        return job, True
    except Exception as exc:  # noqa: BLE001
        repository.fail_judging_job(job.id, error=f"task enqueue failed: {exc}")
        raise


def enqueue_judging_task(
    settings: Settings,
    *,
    job_id: str,
    submission_id: str,
) -> None:
    project = cloud_tasks_project(settings)
    if not project or not settings.cloud_tasks_location or not settings.cloud_tasks_queue:
        raise RuntimeError("Cloud Tasks queue is not configured.")

    queue_path = (
        f"projects/{project}/locations/{settings.cloud_tasks_location}/queues/{settings.cloud_tasks_queue}"
    )
    task_id = f"{job_id}-{submission_id}"
    task_url = f"https://cloudtasks.googleapis.com/v2/{queue_path}/tasks"
    callback_url = f"{settings.app_url.rstrip('/')}/internal/tasks/judging"
    payload = {"job_id": job_id, "submission_id": submission_id}
    body = {
        "task": {
            "name": f"{queue_path}/tasks/{task_id}",
            "dispatchDeadline": "120s",
            "httpRequest": {
                "httpMethod": "POST",
                "url": callback_url,
                "headers": {
                    "Content-Type": "application/json",
                    "X-Task-Token": settings.cloud_tasks_token,
                },
                "body": base64.b64encode(json.dumps(payload).encode("utf-8")).decode("ascii"),
            },
        }
    }

    session = _authorized_session()
    for index, backoff in enumerate((0.0, *TASK_CREATE_RETRY_SECONDS)):
        if backoff:
            time.sleep(backoff)
        response = session.post(task_url, json=body, timeout=30)
        if response.status_code < 300:
            return
        if response.status_code == 409:
            return
        if response.status_code not in {408, 429, 500, 502, 503, 504} or index == len(TASK_CREATE_RETRY_SECONDS):
            response.raise_for_status()
    raise RuntimeError("Unexpected Cloud Tasks enqueue failure.")


def _authorized_session() -> AuthorizedSession:
    credentials, _project = google.auth.default(
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
    )
    return AuthorizedSession(credentials)


def verify_task_token(
    provided_token: str | None,
    settings: Settings,
) -> None:
    if not settings.cloud_tasks_token:
        raise PermissionError("Cloud Tasks token is not configured.")
    if provided_token != settings.cloud_tasks_token:
        raise PermissionError("Invalid task token.")
