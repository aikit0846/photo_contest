from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from datetime import timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(slots=True)
class EventRecord:
    id: str
    title: str
    subtitle: str
    venue: str
    event_date: str
    submissions_open: bool
    provider_preference: str
    model_hint: str | None
    created_at: datetime
    updated_at: datetime


@dataclass(slots=True)
class ScoreRecord:
    id: str
    submission_id: str
    provider: str
    model_name: str
    total_score: float
    composition_score: float
    emotion_score: float
    story_score: float
    couple_focus_score: float
    wedding_mood_score: float
    summary: str
    raw_payload: str
    judged_at: datetime


@dataclass(slots=True)
class SubmissionRecord:
    id: str
    guest_id: str
    guest_name_snapshot: str
    caption: str | None
    storage_key: str
    original_filename: str
    mime_type: str
    sha256: str
    width: int | None
    height: int | None
    file_size_bytes: int
    judging_state: str
    judge_error: str | None
    is_excluded: bool
    excluded_reason: str | None
    admin_score_adjustment: float
    display_order: int | None
    created_at: datetime
    updated_at: datetime
    score: ScoreRecord | None = None
    guest: GuestRecord | None = None

    @property
    def image_url(self) -> str:
        version = int(self.updated_at.timestamp()) if self.updated_at else 0
        return f"/submissions/{self.id}/image?v={version}"


@dataclass(slots=True)
class GuestRecord:
    id: str
    name: str
    display_name: str | None
    table_name: str | None
    group_type: str
    eligible: bool
    invite_token: str
    notes: str | None
    created_at: datetime
    updated_at: datetime
    submission: SubmissionRecord | None = None

    @property
    def label(self) -> str:
        return self.display_name or self.name
