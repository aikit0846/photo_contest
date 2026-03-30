from __future__ import annotations

import secrets
import uuid
from collections.abc import Iterable
from dataclasses import asdict
from datetime import datetime
from functools import lru_cache
import json
from typing import Protocol

from google.cloud import firestore
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from app.config import Settings
from app.config import get_settings
from app.database import SessionLocal
from app.domain import EventRecord
from app.domain import GuestRecord
from app.domain import JudgingJobRecord
from app.domain import ScoreRecord
from app.domain import SubmissionRecord
from app.domain import utcnow
from app import models as sql_models


def _dt(value: datetime | str | None) -> datetime:
    if value is None:
        return utcnow()
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(value)


def _sort_guests(guests: Iterable[GuestRecord]) -> list[GuestRecord]:
    return sorted(
        guests,
        key=lambda guest: (
            guest.side.lower(),
            guest.group_type.lower(),
            (guest.reading or guest.name).lower(),
            guest.name.lower(),
        ),
    )


def _sort_submissions(submissions: Iterable[SubmissionRecord]) -> list[SubmissionRecord]:
    return sorted(submissions, key=lambda item: item.created_at, reverse=True)


class ContestRepository(Protocol):
    def ensure_default_event(self, settings: Settings) -> EventRecord: ...

    def update_event(
        self,
        *,
        submissions_open: bool | None = None,
        feedback_released: bool | None = None,
        provider_preference: str | None = None,
        model_hint: str | None = None,
    ) -> EventRecord: ...

    def create_guest(
        self,
        *,
        name: str,
        side: str,
        table_name: str | None,
        group_type: str,
        eligible: bool,
        display_name: str | None = None,
        reading: str | None = None,
        notes: str | None = None,
    ) -> GuestRecord: ...

    def list_guests(self) -> list[GuestRecord]: ...

    def get_guest_by_token(self, token: str) -> GuestRecord | None: ...

    def get_guest_by_id(self, guest_id: str) -> GuestRecord | None: ...

    def set_guest_eligibility(self, guest_id: str, eligible: bool) -> GuestRecord: ...

    def update_guest(
        self,
        guest_id: str,
        *,
        name: str,
        side: str,
        table_name: str | None,
        group_type: str,
        eligible: bool,
        display_name: str | None = None,
        reading: str | None = None,
        notes: str | None = None,
    ) -> GuestRecord: ...

    def delete_guest(self, guest_id: str) -> None: ...

    def create_judging_job(
        self,
        *,
        provider_name: str,
        total_count: int,
    ) -> JudgingJobRecord: ...

    def get_judging_job(self, job_id: str) -> JudgingJobRecord | None: ...

    def get_active_judging_job(self) -> JudgingJobRecord | None: ...

    def mark_judging_job_running(self, job_id: str, *, total_count: int) -> JudgingJobRecord: ...

    def advance_judging_job(
        self,
        job_id: str,
        *,
        submission_id: str,
        success: bool,
        error: str | None = None,
    ) -> JudgingJobRecord: ...

    def fail_judging_job(self, job_id: str, *, error: str) -> JudgingJobRecord: ...

    def list_submissions(self) -> list[SubmissionRecord]: ...

    def get_submission(self, submission_id: str) -> SubmissionRecord | None: ...

    def upsert_submission(
        self,
        *,
        guest_id: str,
        guest_name_snapshot: str,
        caption: str | None,
        storage_key: str,
        original_filename: str,
        mime_type: str,
        sha256: str,
        width: int | None,
        height: int | None,
        file_size_bytes: int,
    ) -> SubmissionRecord: ...

    def mark_submission_judged(self, submission_id: str, score: ScoreRecord) -> SubmissionRecord: ...

    def mark_submission_failed(self, submission_id: str, error: str) -> SubmissionRecord: ...

    def set_submission_exclusion(
        self,
        submission_id: str,
        *,
        is_excluded: bool,
        reason: str | None,
    ) -> SubmissionRecord: ...

    def update_submission_adjustment(
        self,
        submission_id: str,
        *,
        admin_score_adjustment: float,
    ) -> SubmissionRecord: ...

    def update_submission_system_adjustment(
        self,
        submission_id: str,
        *,
        system_score_adjustment: float,
    ) -> SubmissionRecord: ...


class SqliteContestRepository:
    def _guest_stub(self, value: sql_models.Guest) -> GuestRecord:
        return GuestRecord(
            id=str(value.id),
            name=value.name,
            display_name=value.display_name,
            reading=value.reading,
            side=value.side,
            table_name=value.table_name,
            group_type=value.group_type,
            eligible=value.eligible,
            invite_token=value.invite_token,
            notes=value.notes,
            created_at=_dt(value.created_at),
            updated_at=_dt(value.updated_at),
            submission=None,
        )

    def _event_record(self, value: sql_models.Event) -> EventRecord:
        return EventRecord(
            id=str(value.id),
            title=value.title,
            subtitle=value.subtitle,
            venue=value.venue,
            event_date=value.event_date,
            submissions_open=value.submissions_open,
            feedback_released=value.feedback_released,
            provider_preference=value.provider_preference,
            model_hint=value.model_hint,
            created_at=_dt(value.created_at),
            updated_at=_dt(value.updated_at),
        )

    def _judging_job_record(self, value: sql_models.JudgingJob) -> JudgingJobRecord:
        return JudgingJobRecord(
            id=value.id,
            state=value.state,
            provider_name=value.provider_name,
            total_count=int(value.total_count),
            processed_count=int(value.processed_count),
            success_count=int(value.success_count),
            error_count=int(value.error_count),
            latest_error=value.latest_error,
            processed_submission_ids=json.loads(value.processed_submission_ids or "[]"),
            created_at=_dt(value.created_at),
            updated_at=_dt(value.updated_at),
            started_at=_dt(value.started_at) if value.started_at is not None else None,
            finished_at=_dt(value.finished_at) if value.finished_at is not None else None,
        )

    def _score_record(self, value: sql_models.Score) -> ScoreRecord:
        return ScoreRecord(
            id=str(value.id),
            submission_id=str(value.submission_id),
            provider=value.provider,
            model_name=value.model_name,
            total_score=float(value.total_score),
            composition_score=float(value.composition_score),
            emotion_score=float(value.emotion_score),
            story_score=float(value.story_score),
            couple_focus_score=float(value.couple_focus_score),
            wedding_mood_score=float(value.wedding_mood_score),
            positive_comment_1=value.positive_comment_1,
            positive_comment_2=value.positive_comment_2,
            positive_comment_3=value.positive_comment_3,
            improvement_comment=value.improvement_comment,
            summary=value.summary,
            raw_payload=value.raw_payload,
            judged_at=_dt(value.judged_at),
        )

    def _submission_record(self, value: sql_models.Submission) -> SubmissionRecord:
        return SubmissionRecord(
            id=str(value.id),
            guest_id=str(value.guest_id),
            guest_name_snapshot=value.guest_name_snapshot,
            caption=value.caption,
            storage_key=value.file_path,
            original_filename=value.original_filename,
            mime_type=value.mime_type,
            sha256=value.sha256,
            width=value.width,
            height=value.height,
            file_size_bytes=value.file_size_bytes,
            judging_state=value.judging_state,
            judge_error=value.judge_error,
            is_excluded=value.is_excluded,
            excluded_reason=value.excluded_reason,
            system_score_adjustment=float(value.system_score_adjustment),
            admin_score_adjustment=float(value.admin_score_adjustment),
            created_at=_dt(value.created_at),
            updated_at=_dt(value.updated_at),
            score=self._score_record(value.score) if value.score is not None else None,
            guest=self._guest_stub(value.guest) if getattr(value, "guest", None) is not None else None,
        )

    def _guest_record(self, value: sql_models.Guest) -> GuestRecord:
        return GuestRecord(
            id=str(value.id),
            name=value.name,
            display_name=value.display_name,
            reading=value.reading,
            side=value.side,
            table_name=value.table_name,
            group_type=value.group_type,
            eligible=value.eligible,
            invite_token=value.invite_token,
            notes=value.notes,
            created_at=_dt(value.created_at),
            updated_at=_dt(value.updated_at),
            submission=self._submission_record(value.submission) if value.submission is not None else None,
        )

    def ensure_default_event(self, settings: Settings) -> EventRecord:
        with SessionLocal() as session:
            event = session.get(sql_models.Event, 1)
            if event is None:
                event = sql_models.Event(
                    id=1,
                    title=settings.default_event_title,
                    subtitle=settings.default_event_subtitle,
                    venue=settings.default_venue,
                    event_date=settings.default_event_date,
                    submissions_open=True,
                    feedback_released=False,
                    provider_preference=settings.ai_provider,
                    model_hint=None,
                )
                session.add(event)
                session.commit()
                session.refresh(event)
            return self._event_record(event)

    def update_event(
        self,
        *,
        submissions_open: bool | None = None,
        feedback_released: bool | None = None,
        provider_preference: str | None = None,
        model_hint: str | None = None,
    ) -> EventRecord:
        with SessionLocal() as session:
            event = session.get(sql_models.Event, 1)
            if event is None:
                event = sql_models.Event(id=1, title="", subtitle="", venue="", event_date="")
                session.add(event)
            if submissions_open is not None:
                event.submissions_open = submissions_open
            if feedback_released is not None:
                event.feedback_released = feedback_released
            if provider_preference is not None:
                event.provider_preference = provider_preference
            if model_hint is not None or provider_preference is not None:
                event.model_hint = model_hint
            session.commit()
            session.refresh(event)
            return self._event_record(event)

    def create_guest(
        self,
        *,
        name: str,
        side: str,
        table_name: str | None,
        group_type: str,
        eligible: bool,
        display_name: str | None = None,
        reading: str | None = None,
        notes: str | None = None,
    ) -> GuestRecord:
        with SessionLocal() as session:
            guest = sql_models.Guest(
                name=name.strip(),
                display_name=(display_name or "").strip() or None,
                reading=(reading or "").strip() or None,
                side=side,
                table_name=(table_name or "").strip() or None,
                group_type=group_type,
                eligible=eligible,
                notes=(notes or "").strip() or None,
                invite_token=secrets.token_urlsafe(9),
            )
            session.add(guest)
            session.commit()
            statement = (
                select(sql_models.Guest)
                .options(joinedload(sql_models.Guest.submission).joinedload(sql_models.Submission.score))
                .where(sql_models.Guest.id == guest.id)
            )
            return self._guest_record(session.scalar(statement))

    def list_guests(self) -> list[GuestRecord]:
        with SessionLocal() as session:
            statement = (
                select(sql_models.Guest)
                .options(joinedload(sql_models.Guest.submission).joinedload(sql_models.Submission.score))
            )
            guests = [self._guest_record(item) for item in session.scalars(statement).all()]
            return _sort_guests(guests)

    def get_guest_by_token(self, token: str) -> GuestRecord | None:
        with SessionLocal() as session:
            statement = (
                select(sql_models.Guest)
                .options(joinedload(sql_models.Guest.submission).joinedload(sql_models.Submission.score))
                .where(sql_models.Guest.invite_token == token)
            )
            guest = session.scalar(statement)
            return self._guest_record(guest) if guest is not None else None

    def get_guest_by_id(self, guest_id: str) -> GuestRecord | None:
        with SessionLocal() as session:
            statement = (
                select(sql_models.Guest)
                .options(joinedload(sql_models.Guest.submission).joinedload(sql_models.Submission.score))
                .where(sql_models.Guest.id == int(guest_id))
            )
            guest = session.scalar(statement)
            return self._guest_record(guest) if guest is not None else None

    def set_guest_eligibility(self, guest_id: str, eligible: bool) -> GuestRecord:
        with SessionLocal() as session:
            guest = session.get(sql_models.Guest, int(guest_id))
            if guest is None:
                raise KeyError(guest_id)
            guest.eligible = eligible
            session.commit()
            statement = (
                select(sql_models.Guest)
                .options(joinedload(sql_models.Guest.submission).joinedload(sql_models.Submission.score))
                .where(sql_models.Guest.id == guest.id)
            )
            return self._guest_record(session.scalar(statement))

    def update_guest(
        self,
        guest_id: str,
        *,
        name: str,
        side: str,
        table_name: str | None,
        group_type: str,
        eligible: bool,
        display_name: str | None = None,
        reading: str | None = None,
        notes: str | None = None,
    ) -> GuestRecord:
        with SessionLocal() as session:
            guest = session.get(sql_models.Guest, int(guest_id))
            if guest is None:
                raise KeyError(guest_id)
            guest.name = name.strip()
            guest.display_name = (display_name or "").strip() or None
            guest.reading = (reading or "").strip() or None
            guest.side = side
            guest.table_name = (table_name or "").strip() or None
            guest.group_type = group_type
            guest.eligible = eligible
            guest.notes = (notes or "").strip() or None
            session.commit()
            statement = (
                select(sql_models.Guest)
                .options(joinedload(sql_models.Guest.submission).joinedload(sql_models.Submission.score))
                .where(sql_models.Guest.id == guest.id)
            )
            return self._guest_record(session.scalar(statement))

    def delete_guest(self, guest_id: str) -> None:
        with SessionLocal() as session:
            guest = session.get(sql_models.Guest, int(guest_id))
            if guest is None:
                raise KeyError(guest_id)
            session.delete(guest)
            session.commit()

    def create_judging_job(
        self,
        *,
        provider_name: str,
        total_count: int,
    ) -> JudgingJobRecord:
        with SessionLocal() as session:
            job = sql_models.JudgingJob(
                id=uuid.uuid4().hex,
                state="queued",
                provider_name=provider_name,
                total_count=total_count,
                processed_count=0,
                success_count=0,
                error_count=0,
                processed_submission_ids="[]",
            )
            session.add(job)
            session.commit()
            session.refresh(job)
            return self._judging_job_record(job)

    def get_judging_job(self, job_id: str) -> JudgingJobRecord | None:
        with SessionLocal() as session:
            job = session.get(sql_models.JudgingJob, job_id)
            return self._judging_job_record(job) if job is not None else None

    def get_active_judging_job(self) -> JudgingJobRecord | None:
        with SessionLocal() as session:
            statement = (
                select(sql_models.JudgingJob)
                .where(sql_models.JudgingJob.state.in_(("queued", "running")))
                .order_by(sql_models.JudgingJob.created_at.desc())
            )
            job = session.scalars(statement).first()
            return self._judging_job_record(job) if job is not None else None

    def mark_judging_job_running(self, job_id: str, *, total_count: int) -> JudgingJobRecord:
        with SessionLocal() as session:
            job = session.get(sql_models.JudgingJob, job_id)
            if job is None:
                raise KeyError(job_id)
            now = utcnow()
            job.state = "running"
            job.total_count = total_count
            if job.started_at is None:
                job.started_at = now
            job.updated_at = now
            session.commit()
            session.refresh(job)
            return self._judging_job_record(job)

    def advance_judging_job(
        self,
        job_id: str,
        *,
        submission_id: str,
        success: bool,
        error: str | None = None,
    ) -> JudgingJobRecord:
        with SessionLocal() as session:
            job = session.get(sql_models.JudgingJob, job_id)
            if job is None:
                raise KeyError(job_id)
            processed_submission_ids = json.loads(job.processed_submission_ids or "[]")
            if submission_id in processed_submission_ids:
                return self._judging_job_record(job)
            now = utcnow()
            if job.started_at is None:
                job.started_at = now
            job.state = "running"
            processed_submission_ids.append(submission_id)
            job.processed_submission_ids = json.dumps(processed_submission_ids)
            job.processed_count += 1
            if success:
                job.success_count += 1
            else:
                job.error_count += 1
                job.latest_error = error
            if job.processed_count >= job.total_count:
                job.state = "completed"
                job.finished_at = now
            job.updated_at = now
            session.commit()
            session.refresh(job)
            return self._judging_job_record(job)

    def fail_judging_job(self, job_id: str, *, error: str) -> JudgingJobRecord:
        with SessionLocal() as session:
            job = session.get(sql_models.JudgingJob, job_id)
            if job is None:
                raise KeyError(job_id)
            now = utcnow()
            job.state = "failed"
            job.latest_error = error
            job.finished_at = now
            job.updated_at = now
            session.commit()
            session.refresh(job)
            return self._judging_job_record(job)

    def list_submissions(self) -> list[SubmissionRecord]:
        with SessionLocal() as session:
            statement = select(sql_models.Submission).options(
                joinedload(sql_models.Submission.score),
                joinedload(sql_models.Submission.guest),
            )
            submissions = [self._submission_record(item) for item in session.scalars(statement).all()]
            return _sort_submissions(submissions)

    def get_submission(self, submission_id: str) -> SubmissionRecord | None:
        with SessionLocal() as session:
            statement = (
                select(sql_models.Submission)
                .options(joinedload(sql_models.Submission.score), joinedload(sql_models.Submission.guest))
                .where(sql_models.Submission.id == int(submission_id))
            )
            submission = session.scalar(statement)
            return self._submission_record(submission) if submission is not None else None

    def _existing_submission_for_guest(
        self,
        guest_id: str,
        session,
    ) -> sql_models.Submission | None:
        statement = (
            select(sql_models.Submission)
            .options(joinedload(sql_models.Submission.score))
            .where(sql_models.Submission.guest_id == int(guest_id))
        )
        return session.scalar(statement)

    def upsert_submission(
        self,
        *,
        guest_id: str,
        guest_name_snapshot: str,
        caption: str | None,
        storage_key: str,
        original_filename: str,
        mime_type: str,
        sha256: str,
        width: int | None,
        height: int | None,
        file_size_bytes: int,
    ) -> SubmissionRecord:
        with SessionLocal() as session:
            submission = self._existing_submission_for_guest(guest_id, session)
            if submission is None:
                submission = sql_models.Submission(
                    guest_id=int(guest_id),
                    guest_name_snapshot=guest_name_snapshot,
                    caption=caption,
                    file_path=storage_key,
                    original_filename=original_filename,
                    mime_type=mime_type,
                    sha256=sha256,
                    width=width,
                    height=height,
                    file_size_bytes=file_size_bytes,
                    judging_state="pending",
                )
                session.add(submission)
            else:
                submission.guest_name_snapshot = guest_name_snapshot
                submission.caption = caption
                submission.file_path = storage_key
                submission.original_filename = original_filename
                submission.mime_type = mime_type
                submission.sha256 = sha256
                submission.width = width
                submission.height = height
                submission.file_size_bytes = file_size_bytes
                submission.judging_state = "pending"
                submission.judge_error = None
                submission.is_excluded = False
                submission.excluded_reason = None
                submission.admin_score_adjustment = 0.0
                if submission.score is not None:
                    session.delete(submission.score)
            session.commit()
            statement = (
                select(sql_models.Submission)
                .options(joinedload(sql_models.Submission.score))
                .where(sql_models.Submission.id == submission.id)
            )
            return self._submission_record(session.scalar(statement))

    def mark_submission_judged(self, submission_id: str, score: ScoreRecord) -> SubmissionRecord:
        with SessionLocal() as session:
            submission = self._existing_submission_for_id(submission_id, session)
            if submission.score is None:
                submission.score = sql_models.Score(
                    provider=score.provider,
                    model_name=score.model_name,
                    total_score=score.total_score,
                    composition_score=score.composition_score,
                    emotion_score=score.emotion_score,
                    story_score=score.story_score,
                    couple_focus_score=score.couple_focus_score,
                    wedding_mood_score=score.wedding_mood_score,
                    positive_comment_1=score.positive_comment_1,
                    positive_comment_2=score.positive_comment_2,
                    positive_comment_3=score.positive_comment_3,
                    improvement_comment=score.improvement_comment,
                    summary=score.summary,
                    raw_payload=score.raw_payload,
                    judged_at=score.judged_at,
                )
            else:
                submission.score.provider = score.provider
                submission.score.model_name = score.model_name
                submission.score.total_score = score.total_score
                submission.score.composition_score = score.composition_score
                submission.score.emotion_score = score.emotion_score
                submission.score.story_score = score.story_score
                submission.score.couple_focus_score = score.couple_focus_score
                submission.score.wedding_mood_score = score.wedding_mood_score
                submission.score.positive_comment_1 = score.positive_comment_1
                submission.score.positive_comment_2 = score.positive_comment_2
                submission.score.positive_comment_3 = score.positive_comment_3
                submission.score.improvement_comment = score.improvement_comment
                submission.score.summary = score.summary
                submission.score.raw_payload = score.raw_payload
                submission.score.judged_at = score.judged_at
            submission.judging_state = "judged"
            submission.judge_error = None
            session.commit()
            statement = (
                select(sql_models.Submission)
                .options(joinedload(sql_models.Submission.score))
                .where(sql_models.Submission.id == submission.id)
            )
            return self._submission_record(session.scalar(statement))

    def _existing_submission_for_id(self, submission_id: str, session) -> sql_models.Submission:
        statement = (
            select(sql_models.Submission)
            .options(joinedload(sql_models.Submission.score))
            .where(sql_models.Submission.id == int(submission_id))
        )
        submission = session.scalar(statement)
        if submission is None:
            raise KeyError(submission_id)
        return submission

    def mark_submission_failed(self, submission_id: str, error: str) -> SubmissionRecord:
        with SessionLocal() as session:
            submission = self._existing_submission_for_id(submission_id, session)
            submission.judging_state = "failed"
            submission.judge_error = error
            session.commit()
            return self._submission_record(submission)

    def set_submission_exclusion(
        self,
        submission_id: str,
        *,
        is_excluded: bool,
        reason: str | None,
    ) -> SubmissionRecord:
        with SessionLocal() as session:
            submission = self._existing_submission_for_id(submission_id, session)
            submission.is_excluded = is_excluded
            submission.excluded_reason = reason
            session.commit()
            return self._submission_record(submission)

    def update_submission_adjustment(
        self,
        submission_id: str,
        *,
        admin_score_adjustment: float,
    ) -> SubmissionRecord:
        with SessionLocal() as session:
            submission = self._existing_submission_for_id(submission_id, session)
            submission.admin_score_adjustment = admin_score_adjustment
            session.commit()
            return self._submission_record(submission)

    def update_submission_system_adjustment(
        self,
        submission_id: str,
        *,
        system_score_adjustment: float,
    ) -> SubmissionRecord:
        with SessionLocal() as session:
            submission = self._existing_submission_for_id(submission_id, session)
            submission.system_score_adjustment = system_score_adjustment
            session.commit()
            return self._submission_record(submission)


class FirestoreContestRepository:
    def __init__(self, settings: Settings) -> None:
        self.client = firestore.Client(
            project=settings.firestore_project or None,
            database=settings.firestore_database or None,
        )
        self.events = self.client.collection("events")
        self.judging_jobs = self.client.collection("judging_jobs")
        self.guests = self.client.collection("guests")
        self.submissions = self.client.collection("submissions")

    def _event_record(self, document_id: str, data: dict) -> EventRecord:
        return EventRecord(
            id=document_id,
            title=data["title"],
            subtitle=data["subtitle"],
            venue=data["venue"],
            event_date=data["event_date"],
            submissions_open=bool(data.get("submissions_open", True)),
            feedback_released=bool(data.get("feedback_released", False)),
            provider_preference=data.get("provider_preference", "auto"),
            model_hint=data.get("model_hint"),
            created_at=_dt(data.get("created_at")),
            updated_at=_dt(data.get("updated_at")),
        )

    def _judging_job_record(self, document_id: str, data: dict) -> JudgingJobRecord:
        return JudgingJobRecord(
            id=document_id,
            state=data.get("state", "queued"),
            provider_name=data.get("provider_name", ""),
            total_count=int(data.get("total_count", 0)),
            processed_count=int(data.get("processed_count", 0)),
            success_count=int(data.get("success_count", 0)),
            error_count=int(data.get("error_count", 0)),
            latest_error=data.get("latest_error"),
            processed_submission_ids=[str(item) for item in data.get("processed_submission_ids", [])],
            created_at=_dt(data.get("created_at")),
            updated_at=_dt(data.get("updated_at")),
            started_at=_dt(data.get("started_at")) if data.get("started_at") is not None else None,
            finished_at=_dt(data.get("finished_at")) if data.get("finished_at") is not None else None,
        )

    def _score_record(self, submission_id: str, data: dict | None) -> ScoreRecord | None:
        if not data:
            return None
        return ScoreRecord(
            id=str(data.get("id") or f"score-{submission_id}"),
            submission_id=submission_id,
            provider=data["provider"],
            model_name=data["model_name"],
            total_score=float(data["total_score"]),
            composition_score=float(data["composition_score"]),
            emotion_score=float(data["emotion_score"]),
            story_score=float(data["story_score"]),
            couple_focus_score=float(data["couple_focus_score"]),
            wedding_mood_score=float(data["wedding_mood_score"]),
            positive_comment_1=data.get("positive_comment_1", ""),
            positive_comment_2=data.get("positive_comment_2", ""),
            positive_comment_3=data.get("positive_comment_3", ""),
            improvement_comment=data.get("improvement_comment", ""),
            summary=data.get("summary", data.get("positive_comment_1", "")),
            raw_payload=data["raw_payload"],
            judged_at=_dt(data.get("judged_at")),
        )

    def _submission_record(self, document_id: str, data: dict) -> SubmissionRecord:
        return SubmissionRecord(
            id=document_id,
            guest_id=data["guest_id"],
            guest_name_snapshot=data["guest_name_snapshot"],
            caption=data.get("caption"),
            storage_key=data["storage_key"],
            original_filename=data["original_filename"],
            mime_type=data["mime_type"],
            sha256=data["sha256"],
            width=data.get("width"),
            height=data.get("height"),
            file_size_bytes=int(data["file_size_bytes"]),
            judging_state=data.get("judging_state", "pending"),
            judge_error=data.get("judge_error"),
            is_excluded=bool(data.get("is_excluded", False)),
            excluded_reason=data.get("excluded_reason"),
            system_score_adjustment=float(data.get("system_score_adjustment", 0.0)),
            admin_score_adjustment=float(data.get("admin_score_adjustment", 0.0)),
            created_at=_dt(data.get("created_at")),
            updated_at=_dt(data.get("updated_at")),
            score=self._score_record(document_id, data.get("score")),
        )

    def _guest_record(self, document_id: str, data: dict, submission: SubmissionRecord | None) -> GuestRecord:
        return GuestRecord(
            id=document_id,
            name=data["name"],
            display_name=data.get("display_name"),
            reading=data.get("reading"),
            side=data.get("side", "groom"),
            table_name=data.get("table_name"),
            group_type=data.get("group_type", "friend"),
            eligible=bool(data.get("eligible", True)),
            invite_token=data["invite_token"],
            notes=data.get("notes"),
            created_at=_dt(data.get("created_at")),
            updated_at=_dt(data.get("updated_at")),
            submission=submission,
        )

    def ensure_default_event(self, settings: Settings) -> EventRecord:
        doc = self.events.document("primary")
        snapshot = doc.get()
        if snapshot.exists:
            return self._event_record(snapshot.id, snapshot.to_dict())
        now = utcnow()
        payload = {
            "title": settings.default_event_title,
            "subtitle": settings.default_event_subtitle,
            "venue": settings.default_venue,
            "event_date": settings.default_event_date,
            "submissions_open": True,
            "feedback_released": False,
            "provider_preference": settings.ai_provider,
            "model_hint": None,
            "created_at": now,
            "updated_at": now,
        }
        doc.set(payload)
        return self._event_record("primary", payload)

    def update_event(
        self,
        *,
        submissions_open: bool | None = None,
        feedback_released: bool | None = None,
        provider_preference: str | None = None,
        model_hint: str | None = None,
    ) -> EventRecord:
        doc = self.events.document("primary")
        existing = doc.get().to_dict() or {}
        patch = {"updated_at": utcnow()}
        if submissions_open is not None:
            patch["submissions_open"] = submissions_open
        if feedback_released is not None:
            patch["feedback_released"] = feedback_released
        if provider_preference is not None:
            patch["provider_preference"] = provider_preference
        if model_hint is not None or provider_preference is not None:
            patch["model_hint"] = model_hint
        doc.set(patch, merge=True)
        existing.update(patch)
        return self._event_record("primary", existing)

    def _generate_unique_invite_token(self) -> str:
        for _ in range(5):
            token = secrets.token_urlsafe(9)
            query = self.guests.where("invite_token", "==", token).limit(1).stream()
            if next(iter(query), None) is None:
                return token
        raise RuntimeError("Unable to generate unique invite token.")

    def create_guest(
        self,
        *,
        name: str,
        side: str,
        table_name: str | None,
        group_type: str,
        eligible: bool,
        display_name: str | None = None,
        reading: str | None = None,
        notes: str | None = None,
    ) -> GuestRecord:
        guest_id = uuid.uuid4().hex
        now = utcnow()
        payload = {
            "name": name.strip(),
            "display_name": (display_name or "").strip() or None,
            "reading": (reading or "").strip() or None,
            "side": side,
            "table_name": (table_name or "").strip() or None,
            "group_type": group_type,
            "eligible": eligible,
            "invite_token": self._generate_unique_invite_token(),
            "notes": (notes or "").strip() or None,
            "created_at": now,
            "updated_at": now,
        }
        self.guests.document(guest_id).set(payload)
        return self._guest_record(guest_id, payload, None)

    def _submission_map(self) -> dict[str, SubmissionRecord]:
        return {
            snapshot.id: self._submission_record(snapshot.id, snapshot.to_dict())
            for snapshot in self.submissions.stream()
        }

    def list_guests(self) -> list[GuestRecord]:
        submissions = self._submission_map()
        submissions_by_guest = {submission.guest_id: submission for submission in submissions.values()}
        guests = []
        for snapshot in self.guests.stream():
            guests.append(
                self._guest_record(snapshot.id, snapshot.to_dict(), submissions_by_guest.get(snapshot.id)),
            )
        return _sort_guests(guests)

    def get_guest_by_token(self, token: str) -> GuestRecord | None:
        query = self.guests.where("invite_token", "==", token).limit(1).stream()
        snapshot = next(iter(query), None)
        if snapshot is None:
            return None
        submission = next(
            (
                item
                for item in self.list_submissions()
                if item.guest_id == snapshot.id
            ),
            None,
        )
        return self._guest_record(snapshot.id, snapshot.to_dict(), submission)

    def get_guest_by_id(self, guest_id: str) -> GuestRecord | None:
        snapshot = self.guests.document(guest_id).get()
        if not snapshot.exists:
            return None
        submission = next((item for item in self.list_submissions() if item.guest_id == guest_id), None)
        return self._guest_record(snapshot.id, snapshot.to_dict(), submission)

    def set_guest_eligibility(self, guest_id: str, eligible: bool) -> GuestRecord:
        doc = self.guests.document(guest_id)
        snapshot = doc.get()
        if not snapshot.exists:
            raise KeyError(guest_id)
        doc.set({"eligible": eligible, "updated_at": utcnow()}, merge=True)
        data = snapshot.to_dict()
        data["eligible"] = eligible
        data["updated_at"] = utcnow()
        submission = next((item for item in self.list_submissions() if item.guest_id == guest_id), None)
        return self._guest_record(guest_id, data, submission)

    def update_guest(
        self,
        guest_id: str,
        *,
        name: str,
        side: str,
        table_name: str | None,
        group_type: str,
        eligible: bool,
        display_name: str | None = None,
        reading: str | None = None,
        notes: str | None = None,
    ) -> GuestRecord:
        doc = self.guests.document(guest_id)
        snapshot = doc.get()
        if not snapshot.exists:
            raise KeyError(guest_id)
        patch = {
            "name": name.strip(),
            "display_name": (display_name or "").strip() or None,
            "reading": (reading or "").strip() or None,
            "side": side,
            "table_name": (table_name or "").strip() or None,
            "group_type": group_type,
            "eligible": eligible,
            "notes": (notes or "").strip() or None,
            "updated_at": utcnow(),
        }
        doc.set(patch, merge=True)
        data = snapshot.to_dict()
        data.update(patch)
        submission = next((item for item in self.list_submissions() if item.guest_id == guest_id), None)
        return self._guest_record(guest_id, data, submission)

    def delete_guest(self, guest_id: str) -> None:
        snapshot = self.guests.document(guest_id).get()
        if not snapshot.exists:
            raise KeyError(guest_id)
        existing_submission = self._submission_for_guest(guest_id)
        if existing_submission is not None:
            submission_id, _payload = existing_submission
            self.submissions.document(submission_id).delete()
        self.guests.document(guest_id).delete()

    def create_judging_job(
        self,
        *,
        provider_name: str,
        total_count: int,
    ) -> JudgingJobRecord:
        job_id = uuid.uuid4().hex
        now = utcnow()
        payload = {
            "state": "queued",
            "provider_name": provider_name,
            "total_count": total_count,
            "processed_count": 0,
            "success_count": 0,
            "error_count": 0,
            "latest_error": None,
            "processed_submission_ids": [],
            "created_at": now,
            "updated_at": now,
            "started_at": None,
            "finished_at": None,
        }
        self.judging_jobs.document(job_id).set(payload)
        return self._judging_job_record(job_id, payload)

    def get_judging_job(self, job_id: str) -> JudgingJobRecord | None:
        snapshot = self.judging_jobs.document(job_id).get()
        if not snapshot.exists:
            return None
        return self._judging_job_record(snapshot.id, snapshot.to_dict())

    def get_active_judging_job(self) -> JudgingJobRecord | None:
        jobs = [
            self._judging_job_record(snapshot.id, snapshot.to_dict())
            for snapshot in self.judging_jobs.stream()
        ]
        active = [job for job in jobs if job.state in {"queued", "running"}]
        if not active:
            return None
        return sorted(active, key=lambda job: job.created_at, reverse=True)[0]

    def mark_judging_job_running(self, job_id: str, *, total_count: int) -> JudgingJobRecord:
        doc = self.judging_jobs.document(job_id)
        snapshot = doc.get()
        if not snapshot.exists:
            raise KeyError(job_id)
        data = snapshot.to_dict()
        now = utcnow()
        patch = {
            "state": "running",
            "total_count": total_count,
            "updated_at": now,
        }
        if data.get("started_at") is None:
            patch["started_at"] = now
        doc.set(patch, merge=True)
        data.update(patch)
        return self._judging_job_record(job_id, data)

    def advance_judging_job(
        self,
        job_id: str,
        *,
        submission_id: str,
        success: bool,
        error: str | None = None,
    ) -> JudgingJobRecord:
        doc = self.judging_jobs.document(job_id)
        snapshot = doc.get()
        if not snapshot.exists:
            raise KeyError(job_id)
        data = snapshot.to_dict()
        processed_submission_ids = [str(item) for item in data.get("processed_submission_ids", [])]
        if submission_id in processed_submission_ids:
            return self._judging_job_record(job_id, data)
        now = utcnow()
        processed_submission_ids.append(submission_id)
        processed_count = int(data.get("processed_count", 0)) + 1
        success_count = int(data.get("success_count", 0)) + (1 if success else 0)
        error_count = int(data.get("error_count", 0)) + (0 if success else 1)
        patch = {
            "state": "running",
            "processed_count": processed_count,
            "success_count": success_count,
            "error_count": error_count,
            "processed_submission_ids": processed_submission_ids,
            "updated_at": now,
        }
        if data.get("started_at") is None:
            patch["started_at"] = now
        if not success:
            patch["latest_error"] = error
        if processed_count >= int(data.get("total_count", 0)):
            patch["state"] = "completed"
            patch["finished_at"] = now
        doc.set(patch, merge=True)
        data.update(patch)
        return self._judging_job_record(job_id, data)

    def fail_judging_job(self, job_id: str, *, error: str) -> JudgingJobRecord:
        doc = self.judging_jobs.document(job_id)
        snapshot = doc.get()
        if not snapshot.exists:
            raise KeyError(job_id)
        data = snapshot.to_dict()
        now = utcnow()
        patch = {
            "state": "failed",
            "latest_error": error,
            "finished_at": now,
            "updated_at": now,
        }
        doc.set(patch, merge=True)
        data.update(patch)
        return self._judging_job_record(job_id, data)

    def list_submissions(self) -> list[SubmissionRecord]:
        guest_snapshots = {snapshot.id: snapshot.to_dict() for snapshot in self.guests.stream()}
        submissions = [
            self._submission_record(snapshot.id, snapshot.to_dict())
            for snapshot in self.submissions.stream()
        ]
        for submission in submissions:
            guest = guest_snapshots.get(submission.guest_id)
            if guest is not None:
                submission.guest = self._guest_record(submission.guest_id, guest, None)
        return _sort_submissions(submissions)

    def get_submission(self, submission_id: str) -> SubmissionRecord | None:
        snapshot = self.submissions.document(submission_id).get()
        if not snapshot.exists:
            return None
        submission = self._submission_record(snapshot.id, snapshot.to_dict())
        guest_snapshot = self.guests.document(submission.guest_id).get()
        if guest_snapshot.exists:
            submission.guest = self._guest_record(guest_snapshot.id, guest_snapshot.to_dict(), None)
        return submission

    def _submission_for_guest(self, guest_id: str) -> tuple[str, dict] | None:
        query = self.submissions.where("guest_id", "==", guest_id).limit(1).stream()
        snapshot = next(iter(query), None)
        if snapshot is None:
            return None
        return snapshot.id, snapshot.to_dict()

    def upsert_submission(
        self,
        *,
        guest_id: str,
        guest_name_snapshot: str,
        caption: str | None,
        storage_key: str,
        original_filename: str,
        mime_type: str,
        sha256: str,
        width: int | None,
        height: int | None,
        file_size_bytes: int,
    ) -> SubmissionRecord:
        existing = self._submission_for_guest(guest_id)
        now = utcnow()
        payload = {
            "guest_id": guest_id,
            "guest_name_snapshot": guest_name_snapshot,
            "caption": caption,
            "storage_key": storage_key,
            "original_filename": original_filename,
            "mime_type": mime_type,
            "sha256": sha256,
            "width": width,
            "height": height,
            "file_size_bytes": file_size_bytes,
            "judging_state": "pending",
            "judge_error": None,
            "is_excluded": False,
            "excluded_reason": None,
            "system_score_adjustment": 0.0,
            "admin_score_adjustment": 0.0,
            "updated_at": now,
            "score": None,
        }
        if existing is None:
            submission_id = uuid.uuid4().hex
            payload["created_at"] = now
            self.submissions.document(submission_id).set(payload)
        else:
            submission_id, existing_payload = existing
            payload["created_at"] = existing_payload.get("created_at", now)
            self.submissions.document(submission_id).set(payload, merge=True)
        return self._submission_record(submission_id, payload)

    def mark_submission_judged(self, submission_id: str, score: ScoreRecord) -> SubmissionRecord:
        doc = self.submissions.document(submission_id)
        snapshot = doc.get()
        if not snapshot.exists:
            raise KeyError(submission_id)
        data = snapshot.to_dict()
        score_payload = asdict(score)
        doc.set(
            {
                "judging_state": "judged",
                "judge_error": None,
                "updated_at": utcnow(),
                "score": score_payload,
            },
            merge=True,
        )
        data.update(
            {
                "judging_state": "judged",
                "judge_error": None,
                "updated_at": utcnow(),
                "score": score_payload,
            },
        )
        return self._submission_record(submission_id, data)

    def mark_submission_failed(self, submission_id: str, error: str) -> SubmissionRecord:
        doc = self.submissions.document(submission_id)
        snapshot = doc.get()
        if not snapshot.exists:
            raise KeyError(submission_id)
        data = snapshot.to_dict()
        doc.set({"judging_state": "failed", "judge_error": error, "updated_at": utcnow()}, merge=True)
        data.update({"judging_state": "failed", "judge_error": error, "updated_at": utcnow()})
        return self._submission_record(submission_id, data)

    def set_submission_exclusion(
        self,
        submission_id: str,
        *,
        is_excluded: bool,
        reason: str | None,
    ) -> SubmissionRecord:
        doc = self.submissions.document(submission_id)
        snapshot = doc.get()
        if not snapshot.exists:
            raise KeyError(submission_id)
        data = snapshot.to_dict()
        patch = {
            "is_excluded": is_excluded,
            "excluded_reason": reason,
            "updated_at": utcnow(),
        }
        doc.set(patch, merge=True)
        data.update(patch)
        return self._submission_record(submission_id, data)

    def update_submission_adjustment(
        self,
        submission_id: str,
        *,
        admin_score_adjustment: float,
    ) -> SubmissionRecord:
        doc = self.submissions.document(submission_id)
        snapshot = doc.get()
        if not snapshot.exists:
            raise KeyError(submission_id)
        data = snapshot.to_dict()
        patch = {
            "admin_score_adjustment": admin_score_adjustment,
            "updated_at": utcnow(),
        }
        doc.set(patch, merge=True)
        data.update(patch)
        return self._submission_record(submission_id, data)

    def update_submission_system_adjustment(
        self,
        submission_id: str,
        *,
        system_score_adjustment: float,
    ) -> SubmissionRecord:
        doc = self.submissions.document(submission_id)
        snapshot = doc.get()
        if not snapshot.exists:
            raise KeyError(submission_id)
        data = snapshot.to_dict()
        patch = {
            "system_score_adjustment": system_score_adjustment,
            "updated_at": utcnow(),
        }
        doc.set(patch, merge=True)
        data.update(patch)
        return self._submission_record(submission_id, data)


@lru_cache
def get_repository() -> ContestRepository:
    settings = get_settings()
    if settings.data_backend.lower() == "firestore":
        return FirestoreContestRepository(settings)
    return SqliteContestRepository()
