from __future__ import annotations

import mimetypes
from pathlib import Path
from urllib.parse import quote_plus

from fastapi import HTTPException
from fastapi import UploadFile

from app.config import Settings
from app.domain import EventRecord
from app.domain import GuestRecord
from app.domain import ScoreRecord
from app.domain import SubmissionRecord
from app.domain import utcnow
from app.image_utils import analyze_image
from app.repositories import ContestRepository
from app.services.providers import build_provider
from app.services.providers import provider_options
from app.storage import BaseImageStorage


ENTRY_CATEGORY_OPTIONS = [
    {"key": "groom-friend", "label": "新郎友人"},
    {"key": "bride-friend", "label": "新婦友人"},
    {"key": "groom-family", "label": "新郎親族"},
    {"key": "bride-family", "label": "新婦親族"},
]


def common_entry_url(settings: Settings) -> str:
    return f"{settings.app_url.rstrip('/')}/entry"


def entry_category_options() -> list[dict[str, str]]:
    return ENTRY_CATEGORY_OPTIONS


def entry_category_label(category_key: str) -> str:
    for option in ENTRY_CATEGORY_OPTIONS:
        if option["key"] == category_key:
            return option["label"]
    return "該当ゲスト"


def category_for_guest(guest: GuestRecord) -> str:
    return f"{guest.side}-{guest.group_type}"


def guests_for_category(repository: ContestRepository, category_key: str) -> list[GuestRecord]:
    guests = [guest for guest in repository.list_guests() if category_for_guest(guest) == category_key]
    return sorted(guests, key=lambda guest: guest.name)


def default_model_hint(settings: Settings, provider_name: str) -> str | None:
    if provider_name == "gemini":
        return settings.google_model
    if provider_name == "ollama":
        return settings.ollama_model
    return None


def get_event(repository: ContestRepository, settings: Settings) -> EventRecord:
    event = repository.ensure_default_event(settings)
    if not event.model_hint:
        event = repository.update_event(model_hint=default_model_hint(settings, event.provider_preference))
    return event


def create_guest(
    repository: ContestRepository,
    *,
    name: str,
    side: str,
    table_name: str | None,
    group_type: str,
    eligible: bool,
    display_name: str | None = None,
    notes: str | None = None,
) -> GuestRecord:
    return repository.create_guest(
        name=name,
        side=side,
        table_name=table_name,
        group_type=group_type,
        eligible=eligible,
        display_name=display_name,
        notes=notes,
    )


def invite_url(settings: Settings, guest: GuestRecord) -> str:
    return f"{settings.app_url.rstrip('/')}/join/{quote_plus(guest.invite_token)}"


def _pick_extension(upload: UploadFile) -> str:
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic"}:
        return suffix
    guessed = mimetypes.guess_extension(upload.content_type or "")
    if guessed:
        return guessed
    return ".jpg"


def save_submission(
    repository: ContestRepository,
    storage: BaseImageStorage,
    *,
    event: EventRecord,
    guest: GuestRecord,
    upload: UploadFile,
    caption: str | None,
    settings: Settings,
) -> SubmissionRecord:
    if not event.submissions_open:
        raise HTTPException(status_code=400, detail="Submissions are closed.")

    image_bytes = upload.file.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail="Please choose an image file.")
    size_mb = len(image_bytes) / 1024 / 1024
    if size_mb > settings.max_upload_mb:
        raise HTTPException(status_code=400, detail=f"Image is larger than {settings.max_upload_mb} MB.")

    metrics = analyze_image(image_bytes)
    ext = _pick_extension(upload)
    storage_key = f"submissions/{guest.invite_token}/{metrics.sha256[:20]}{ext}"
    previous_storage_key = guest.submission.storage_key if guest.submission else None
    storage.save_image(
        key=storage_key,
        data=image_bytes,
        content_type=upload.content_type or "application/octet-stream",
    )
    if previous_storage_key and previous_storage_key != storage_key:
        storage.delete_image(previous_storage_key)

    return repository.upsert_submission(
        guest_id=guest.id,
        guest_name_snapshot=guest.label,
        caption=(caption or "").strip() or None,
        storage_key=storage_key,
        original_filename=upload.filename or Path(storage_key).name,
        mime_type=upload.content_type or "application/octet-stream",
        sha256=metrics.sha256,
        width=metrics.width,
        height=metrics.height,
        file_size_bytes=len(image_bytes),
    )


def judge_submissions(
    repository: ContestRepository,
    storage: BaseImageStorage,
    *,
    event: EventRecord,
    settings: Settings,
    force: bool = False,
) -> tuple[int, list[str], str]:
    provider = build_provider(settings, event.provider_preference, event.model_hint)
    submissions = repository.list_submissions()
    guests = {guest.id: guest for guest in repository.list_guests()}

    judged = 0
    errors: list[str] = []
    for submission in submissions:
        guest = guests.get(submission.guest_id)
        if guest is None:
            continue
        if not force and submission.judging_state == "judged" and submission.score is not None:
            continue

        try:
            image_bytes = storage.read_image(submission.storage_key)
            result = provider.judge(
                image_bytes=image_bytes,
                mime_type=submission.mime_type,
                guest_name=guest.label,
                table_name=guest.table_name,
            )
            repository.mark_submission_judged(
                submission.id,
                ScoreRecord(
                    id=f"score-{submission.id}",
                    submission_id=submission.id,
                    provider=result.provider,
                    model_name=result.model_name,
                    total_score=result.total_score,
                    composition_score=result.composition,
                    emotion_score=result.emotion,
                    story_score=result.story,
                    couple_focus_score=result.couple_focus,
                    wedding_mood_score=result.wedding_mood,
                    summary=result.summary,
                    raw_payload=result.raw_payload,
                    judged_at=utcnow(),
                ),
            )
            judged += 1
        except Exception as exc:  # noqa: BLE001
            repository.mark_submission_failed(submission.id, str(exc))
            errors.append(f"{guest.label}: {exc}")

    return judged, errors, provider.display_name


def effective_score(submission: SubmissionRecord) -> float:
    if submission.score is None:
        return 0.0
    return round(submission.score.total_score + submission.admin_score_adjustment, 1)


def feedback_score_ceiling(repository: ContestRepository) -> float | None:
    ranked = leaderboard(repository, limit=3)
    if not ranked:
        return None
    return effective_score(ranked[-1])


def feedback_display_score(
    submission: SubmissionRecord,
    *,
    eligible: bool,
    ceiling: float | None,
) -> float:
    raw_score = effective_score(submission)
    if eligible and not submission.is_excluded:
        return raw_score
    if ceiling is None:
        return raw_score
    upper_bound = round(max(0.0, ceiling - 0.1), 1)
    return round(min(raw_score, upper_bound), 1)


def leaderboard(repository: ContestRepository, limit: int | None = None) -> list[SubmissionRecord]:
    guests = {guest.id: guest for guest in repository.list_guests()}
    submissions = repository.list_submissions()
    filtered = []
    for item in submissions:
        guest = guests.get(item.guest_id)
        if guest is None:
            continue
        if item.is_excluded or not guest.eligible or item.score is None or item.judging_state != "judged":
            continue
        filtered.append(item)
    ordered = sorted(
        filtered,
        key=lambda item: (
            -effective_score(item),
            item.created_at,
        ),
    )
    if limit is not None:
        return ordered[:limit]
    return ordered


def provider_status(settings: Settings) -> dict[str, str]:
    return {
        "auto": "Gemini API key があれば Gemini、なければローカル heuristic にフォールバック",
        "mock": "APIキー不要。ローカルの簡易スコアリング",
        "gemini": "Google Gemini API を使って採点",
        "ollama": "ローカルの Ollama モデルを使って採点",
    }


def event_stats(repository: ContestRepository) -> dict[str, int]:
    guests = repository.list_guests()
    submissions = repository.list_submissions()
    scored = sum(1 for item in submissions if item.score is not None and item.judging_state == "judged")
    return {
        "guests": len(guests),
        "eligible_guests": sum(1 for guest in guests if guest.eligible),
        "submissions": len(submissions),
        "scored": scored,
    }


def provider_choices() -> list[str]:
    return provider_options()
