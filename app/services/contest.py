from __future__ import annotations

import mimetypes
import time
from pathlib import Path
from urllib.parse import quote_plus

import httpx
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

GEMINI_FREE_TIER_MIN_INTERVAL_SECONDS = 6.5
GEMINI_BATCH_SIZE = 3
DEFAULT_BATCH_SIZE = 20
GEMINI_RETRY_BACKOFF_SECONDS = (10.0, 20.0)


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


def ranking_target(submission: SubmissionRecord, guest: GuestRecord | None) -> bool:
    return bool(
        guest is not None
        and guest.eligible
        and not submission.is_excluded
        and submission.score is not None
        and submission.judging_state == "judged"
    )


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
    plan = plan_judging_run(repository, event=event, settings=settings, force=force)
    judged, errors, provider_name, _processed = judge_submission_batch(
        repository,
        storage,
        event=event,
        settings=settings,
        submission_ids=plan["submission_ids"],
    )
    return judged, errors, provider_name


def plan_judging_run(
    repository: ContestRepository,
    *,
    event: EventRecord,
    settings: Settings,
    force: bool = False,
) -> dict[str, object]:
    provider = build_provider(settings, event.provider_preference, event.model_hint)
    submission_ids = [submission.id for submission in _judging_targets(repository, force=force)]
    return {
        "submission_ids": submission_ids,
        "total": len(submission_ids),
        "provider_name": provider.display_name,
        "batch_size": GEMINI_BATCH_SIZE if provider.provider_name == "gemini" else DEFAULT_BATCH_SIZE,
        "min_interval_seconds": (
            GEMINI_FREE_TIER_MIN_INTERVAL_SECONDS if provider.provider_name == "gemini" else 0.0
        ),
    }


def judge_submission_batch(
    repository: ContestRepository,
    storage: BaseImageStorage,
    *,
    event: EventRecord,
    settings: Settings,
    submission_ids: list[str],
) -> tuple[int, list[str], str, int]:
    provider = build_provider(settings, event.provider_preference, event.model_hint)
    submission_id_set = set(submission_ids)
    submission_map = {
        submission.id: submission
        for submission in repository.list_submissions()
        if submission.id in submission_id_set
    }
    guests = {guest.id: guest for guest in repository.list_guests()}

    judged = 0
    processed = 0
    errors: list[str] = []
    last_started_at: float | None = None
    min_interval_seconds = (
        GEMINI_FREE_TIER_MIN_INTERVAL_SECONDS if provider.provider_name == "gemini" else 0.0
    )

    for submission_id in submission_ids:
        submission = submission_map.get(submission_id)
        if submission is None:
            errors.append(f"{submission_id}: submission not found")
            processed += 1
            continue
        guest = guests.get(submission.guest_id) or submission.guest
        if guest is None:
            errors.append(f"{submission_id}: guest not found")
            processed += 1
            continue

        if min_interval_seconds and last_started_at is not None:
            elapsed = time.monotonic() - last_started_at
            if elapsed < min_interval_seconds:
                time.sleep(min_interval_seconds - elapsed)
        last_started_at = time.monotonic()

        success, error = _judge_submission_with_provider(
            repository,
            storage,
            provider=provider,
            submission=submission,
            guest=guest,
        )
        if success:
            judged += 1
        elif error is not None:
            errors.append(f"{guest.label}: {error}")
        processed += 1

    refresh_balanced_scores(repository)
    return judged, errors, provider.display_name, processed


def judge_single_submission(
    repository: ContestRepository,
    storage: BaseImageStorage,
    *,
    submission_id: str,
    event: EventRecord,
    settings: Settings,
) -> tuple[bool, str, str | None]:
    provider = build_provider(settings, event.provider_preference, event.model_hint)
    submission = repository.get_submission(submission_id)
    if submission is None:
        return False, provider.display_name, "submission not found"
    guest = submission.guest or repository.get_guest_by_id(submission.guest_id)
    if guest is None:
        return False, provider.display_name, "guest not found"
    success, error = _judge_submission_with_provider(
        repository,
        storage,
        provider=provider,
        submission=submission,
        guest=guest,
    )
    refresh_balanced_scores(repository)
    return success, provider.display_name, error


def _judge_submission_with_provider(
    repository: ContestRepository,
    storage: BaseImageStorage,
    *,
    provider,
    submission: SubmissionRecord,
    guest: GuestRecord,
) -> tuple[bool, str | None]:
    try:
        image_bytes = storage.read_image(submission.storage_key)
        result = _judge_with_retries(
            provider,
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
                positive_comment_1=result.positive_comment_1,
                positive_comment_2=result.positive_comment_2,
                positive_comment_3=result.positive_comment_3,
                improvement_comment=result.improvement_comment,
                summary=result.summary,
                raw_payload=result.raw_payload,
                judged_at=utcnow(),
            ),
        )
        return True, None
    except Exception as exc:  # noqa: BLE001
        repository.mark_submission_failed(submission.id, str(exc))
        return False, str(exc)


def _judge_with_retries(
    provider,
    *,
    image_bytes: bytes,
    mime_type: str,
    guest_name: str,
    table_name: str | None,
):
    backoffs = GEMINI_RETRY_BACKOFF_SECONDS if provider.provider_name == "gemini" else ()
    attempt = 0
    while True:
        try:
            return provider.judge(
                image_bytes=image_bytes,
                mime_type=mime_type,
                guest_name=guest_name,
                table_name=table_name,
            )
        except Exception as exc:  # noqa: BLE001
            if attempt >= len(backoffs) or not _is_retryable_judging_error(exc):
                raise
            time.sleep(backoffs[attempt])
            attempt += 1


def _is_retryable_judging_error(exc: Exception) -> bool:
    if isinstance(exc, httpx.TimeoutException):
        return True
    if isinstance(exc, httpx.TransportError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code in {408, 409, 429, 500, 502, 503, 504}
    return False


def _judging_targets(
    repository: ContestRepository,
    *,
    force: bool,
) -> list[SubmissionRecord]:
    submissions = repository.list_submissions()
    guests = {guest.id: guest for guest in repository.list_guests()}
    targets: list[SubmissionRecord] = []
    for submission in submissions:
        guest = guests.get(submission.guest_id) or submission.guest
        if guest is None:
            continue
        if not force and submission.judging_state == "judged" and submission.score is not None:
            continue
        targets.append(submission)
    return targets


def effective_score(submission: SubmissionRecord) -> float:
    if submission.score is None:
        return 0.0
    return round(
        submission.score.total_score
        + submission.system_score_adjustment
        + submission.admin_score_adjustment,
        1,
    )


def base_score(submission: SubmissionRecord) -> float:
    if submission.score is None:
        return 0.0
    return round(
        submission.score.total_score
        + submission.admin_score_adjustment,
        1,
    )


def score_breakdown(
    submission: SubmissionRecord,
    *,
    target_total: float | None = None,
) -> list[tuple[str, float]]:
    if submission.score is None:
        return []
    labels = ["構図", "表情", "物語性", "主役感", "祝祭感"]
    values = [
        round(submission.score.composition_score, 1),
        round(submission.score.emotion_score, 1),
        round(submission.score.story_score, 1),
        round(submission.score.couple_focus_score, 1),
        round(submission.score.wedding_mood_score, 1),
    ]
    if target_total is None:
        target_total = effective_score(submission)

    units = [int(round(value * 10)) for value in values]
    target_units = int(round(target_total * 10))
    diff_units = target_units - sum(units)
    order = sorted(range(len(units)), key=lambda index: units[index], reverse=True)

    while diff_units > 0:
        changed = False
        for index in order:
            if units[index] < 200:
                units[index] += 1
                diff_units -= 1
                changed = True
                if diff_units == 0:
                    break
        if not changed:
            break

    while diff_units < 0:
        changed = False
        for index in order:
            if units[index] > 0:
                units[index] -= 1
                diff_units += 1
                changed = True
                if diff_units == 0:
                    break
        if not changed:
            break

    return list(zip(labels, [unit / 10 for unit in units]))


def feedback_comments(submission: SubmissionRecord) -> list[str]:
    if submission.score is None:
        return []
    positive = submission.score.positive_comment_1 or submission.score.summary
    improvement = submission.score.improvement_comment
    return [
        positive,
        improvement,
    ]


def short_comment(submission: SubmissionRecord) -> str:
    if submission.score is None:
        return ""
    return submission.score.positive_comment_1 or submission.score.summary


def feedback_lines_for_submission(submission: SubmissionRecord, rank: int | None = None) -> list[str]:
    if rank is not None:
        return podium_comment_lines(submission, rank)
    return feedback_comments(submission)


def podium_comment(submission: SubmissionRecord, rank: int) -> str:
    return " ".join(podium_comment_lines(submission, rank))


def podium_comment_lines(submission: SubmissionRecord, rank: int) -> list[str]:
    if submission.score is None:
        return []
    positives = [
        submission.score.positive_comment_1 or submission.score.summary,
        submission.score.positive_comment_2,
        submission.score.positive_comment_3,
    ]
    improvement = submission.score.improvement_comment
    if rank == 1:
        parts = positives
    elif rank == 2:
        parts = positives[:2] + [improvement]
    else:
        parts = [submission.score.positive_comment_1, improvement]
    return [part for part in parts if part]


def refresh_balanced_scores(repository: ContestRepository) -> None:
    submissions = repository.list_submissions()
    for submission in submissions:
        if submission.system_score_adjustment != 0.0:
            repository.update_submission_system_adjustment(
                submission.id,
                system_score_adjustment=0.0,
            )

    guests = {guest.id: guest for guest in repository.list_guests()}
    refreshed_submissions = repository.list_submissions()
    target_submissions = [
        submission
        for submission in refreshed_submissions
        if ranking_target(submission, guests.get(submission.guest_id))
    ]

    ordered = sorted(
        target_submissions,
        key=lambda item: (
            -base_score(item),
            item.created_at,
        ),
    )
    if len(ordered) < 3:
        return

    top_three = ordered[:3]
    top_sides = {guests[item.guest_id].side for item in top_three if item.guest_id in guests}
    if len(top_sides) > 1:
        return

    required_side = "bride" if next(iter(top_sides)) == "groom" else "groom"
    alternate = next(
        (
            submission
            for submission in ordered[3:]
            if guests.get(submission.guest_id) and guests[submission.guest_id].side == required_side
        ),
        None,
    )
    if alternate is None:
        return

    third_score = base_score(top_three[2])
    target_score = round(third_score + 0.1, 1)
    system_adjustment = round(target_score - base_score(alternate), 1)
    repository.update_submission_system_adjustment(
        alternate.id,
        system_score_adjustment=system_adjustment,
    )


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
        if not ranking_target(item, guest):
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
