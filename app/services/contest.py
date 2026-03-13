from __future__ import annotations

import mimetypes
import os
import secrets
from pathlib import Path
from urllib.parse import quote_plus

from fastapi import HTTPException
from fastapi import UploadFile
from sqlalchemy import Select
from sqlalchemy import select
from sqlalchemy.orm import Session
from sqlalchemy.orm import joinedload

from app.config import Settings
from app.image_utils import analyze_image
from app.models import Event
from app.models import Guest
from app.models import Score
from app.models import Submission
from app.services.providers import build_provider
from app.services.providers import provider_options


def ensure_storage(settings: Settings) -> None:
    settings.data_path.mkdir(parents=True, exist_ok=True)
    settings.upload_path.mkdir(parents=True, exist_ok=True)


def default_model_hint(settings: Settings, provider_name: str) -> str | None:
    if provider_name == "gemini":
        return settings.google_model
    if provider_name == "anthropic":
        return settings.anthropic_model
    if provider_name == "ollama":
        return settings.ollama_model
    return None


def ensure_default_event(session: Session, settings: Settings) -> Event:
    event = session.get(Event, 1)
    if event:
        return event

    event = Event(
        id=1,
        title=settings.default_event_title,
        subtitle=settings.default_event_subtitle,
        venue=settings.default_venue,
        event_date=settings.default_event_date,
        submissions_open=True,
        provider_preference=settings.ai_provider,
        model_hint=default_model_hint(settings, settings.ai_provider),
    )
    session.add(event)
    session.commit()
    session.refresh(event)
    return event


def get_event(session: Session, settings: Settings) -> Event:
    return ensure_default_event(session, settings)


def create_guest(
    session: Session,
    *,
    name: str,
    table_name: str | None,
    group_type: str,
    eligible: bool,
    display_name: str | None = None,
    notes: str | None = None,
) -> Guest:
    guest = Guest(
        name=name.strip(),
        display_name=(display_name or "").strip() or None,
        table_name=(table_name or "").strip() or None,
        group_type=group_type,
        eligible=eligible,
        notes=(notes or "").strip() or None,
        invite_token=secrets.token_urlsafe(9),
    )
    session.add(guest)
    session.commit()
    session.refresh(guest)
    return guest


def invite_url(settings: Settings, guest: Guest) -> str:
    return f"{settings.app_url.rstrip('/')}/join/{quote_plus(guest.invite_token)}"


def guest_query() -> Select[tuple[Guest]]:
    return select(Guest).options(joinedload(Guest.submission).joinedload(Submission.score)).order_by(
        Guest.table_name.asc().nulls_last(),
        Guest.name.asc(),
    )


def submission_query() -> Select[tuple[Submission]]:
    return (
        select(Submission)
        .options(joinedload(Submission.guest), joinedload(Submission.score))
        .order_by(Submission.created_at.desc())
    )


def get_guest_by_token(session: Session, token: str) -> Guest | None:
    statement = (
        select(Guest)
        .options(joinedload(Guest.submission).joinedload(Submission.score))
        .where(Guest.invite_token == token)
    )
    return session.scalar(statement)


def _pick_extension(upload: UploadFile) -> str:
    suffix = Path(upload.filename or "").suffix.lower()
    if suffix in {".jpg", ".jpeg", ".png", ".webp", ".gif", ".heic"}:
        return suffix
    guessed = mimetypes.guess_extension(upload.content_type or "")
    if guessed:
        return guessed
    return ".jpg"


def save_submission(
    session: Session,
    *,
    event: Event,
    guest: Guest,
    upload: UploadFile,
    caption: str | None,
    settings: Settings,
) -> Submission:
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
    filename = f"{guest.invite_token}-{metrics.sha256[:12]}{ext}"
    destination = settings.upload_path / filename
    destination.write_bytes(image_bytes)

    submission = guest.submission
    if submission is None:
        submission = Submission(
            guest=guest,
            guest_name_snapshot=guest.label,
            caption=(caption or "").strip() or None,
            file_path=str(destination),
            original_filename=upload.filename or filename,
            mime_type=upload.content_type or "application/octet-stream",
            sha256=metrics.sha256,
            width=metrics.width,
            height=metrics.height,
            file_size_bytes=len(image_bytes),
            judging_state="pending",
        )
        session.add(submission)
    else:
        old_path = Path(submission.file_path)
        submission.guest_name_snapshot = guest.label
        submission.caption = (caption or "").strip() or None
        submission.file_path = str(destination)
        submission.original_filename = upload.filename or filename
        submission.mime_type = upload.content_type or "application/octet-stream"
        submission.sha256 = metrics.sha256
        submission.width = metrics.width
        submission.height = metrics.height
        submission.file_size_bytes = len(image_bytes)
        submission.judging_state = "pending"
        submission.judge_error = None
        submission.is_excluded = False
        submission.excluded_reason = None
        submission.display_order = None
        submission.admin_score_adjustment = 0.0
        if submission.score is not None:
            session.delete(submission.score)
        if old_path.exists() and old_path != destination:
            old_path.unlink(missing_ok=True)

    session.commit()
    session.refresh(submission)
    return submission


def judge_submissions(
    session: Session,
    *,
    event: Event,
    settings: Settings,
    force: bool = False,
) -> tuple[int, list[str], str]:
    provider = build_provider(settings, event.provider_preference, event.model_hint)
    statement = submission_query()
    submissions = session.scalars(statement).all()

    judged = 0
    errors: list[str] = []
    for submission in submissions:
        if submission.is_excluded:
            continue
        if not submission.guest.eligible:
            continue
        if not force and submission.judging_state == "judged" and submission.score is not None:
            continue

        try:
            image_bytes = Path(submission.file_path).read_bytes()
            result = provider.judge(
                image_bytes=image_bytes,
                mime_type=submission.mime_type,
                caption=submission.caption,
                guest_name=submission.guest.label,
                table_name=submission.guest.table_name,
            )
            if submission.score is None:
                score = Score(
                    submission=submission,
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
                )
                session.add(score)
            else:
                submission.score.provider = result.provider
                submission.score.model_name = result.model_name
                submission.score.total_score = result.total_score
                submission.score.composition_score = result.composition
                submission.score.emotion_score = result.emotion
                submission.score.story_score = result.story
                submission.score.couple_focus_score = result.couple_focus
                submission.score.wedding_mood_score = result.wedding_mood
                submission.score.summary = result.summary
                submission.score.raw_payload = result.raw_payload
            submission.judging_state = "judged"
            submission.judge_error = None
            judged += 1
        except Exception as exc:  # noqa: BLE001
            submission.judging_state = "failed"
            submission.judge_error = str(exc)
            errors.append(f"{submission.guest.label}: {exc}")

    session.commit()
    return judged, errors, provider.display_name


def effective_score(submission: Submission) -> float:
    if submission.score is None:
        return 0.0
    return round(submission.score.total_score + submission.admin_score_adjustment, 1)


def leaderboard(session: Session, limit: int | None = None) -> list[Submission]:
    submissions = session.scalars(submission_query()).all()
    filtered = [
        item
        for item in submissions
        if not item.is_excluded
        and item.guest.eligible
        and item.score is not None
        and item.judging_state == "judged"
    ]
    ordered = sorted(
        filtered,
        key=lambda item: (
            item.display_order is None,
            item.display_order if item.display_order is not None else 9999,
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
        "anthropic": "Claude API を使って採点",
        "ollama": "ローカルの Ollama モデルを使って採点",
    }


def event_stats(session: Session) -> dict[str, int]:
    guests = session.scalars(select(Guest)).all()
    submissions = session.scalars(select(Submission)).all()
    scored = sum(1 for item in submissions if item.score is not None and item.judging_state == "judged")
    return {
        "guests": len(guests),
        "eligible_guests": sum(1 for guest in guests if guest.eligible),
        "submissions": len(submissions),
        "scored": scored,
    }


def provider_choices() -> list[str]:
    return provider_options()


def cleanup_upload(path: str) -> None:
    if path and os.path.exists(path):
        os.unlink(path)
