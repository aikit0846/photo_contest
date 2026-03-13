from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean
from sqlalchemy import DateTime
from sqlalchemy import Float
from sqlalchemy import ForeignKey
from sqlalchemy import Integer
from sqlalchemy import String
from sqlalchemy import Text
from sqlalchemy.orm import Mapped
from sqlalchemy.orm import mapped_column
from sqlalchemy.orm import relationship

from app.database import Base


def utcnow() -> datetime:
    return datetime.utcnow()


class Event(Base):
    __tablename__ = "events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, default=1)
    title: Mapped[str] = mapped_column(String(200))
    subtitle: Mapped[str] = mapped_column(String(200))
    venue: Mapped[str] = mapped_column(String(200))
    event_date: Mapped[str] = mapped_column(String(20))
    submissions_open: Mapped[bool] = mapped_column(Boolean, default=True)
    provider_preference: Mapped[str] = mapped_column(String(50), default="auto")
    model_hint: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class Guest(Base):
    __tablename__ = "guests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(120))
    display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    table_name: Mapped[str | None] = mapped_column(String(80), nullable=True)
    group_type: Mapped[str] = mapped_column(String(20), default="friend")
    eligible: Mapped[bool] = mapped_column(Boolean, default=True)
    invite_token: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    submission: Mapped[Submission | None] = relationship(
        "Submission",
        back_populates="guest",
        uselist=False,
        cascade="all, delete-orphan",
    )

    @property
    def label(self) -> str:
        return self.display_name or self.name


class Submission(Base):
    __tablename__ = "submissions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    guest_id: Mapped[int] = mapped_column(ForeignKey("guests.id", ondelete="CASCADE"), unique=True)
    guest_name_snapshot: Mapped[str] = mapped_column(String(120))
    caption: Mapped[str | None] = mapped_column(Text, nullable=True)
    file_path: Mapped[str] = mapped_column(String(500))
    original_filename: Mapped[str] = mapped_column(String(255))
    mime_type: Mapped[str] = mapped_column(String(80))
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    width: Mapped[int | None] = mapped_column(Integer, nullable=True)
    height: Mapped[int | None] = mapped_column(Integer, nullable=True)
    file_size_bytes: Mapped[int] = mapped_column(Integer)
    judging_state: Mapped[str] = mapped_column(String(20), default="pending")
    judge_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_excluded: Mapped[bool] = mapped_column(Boolean, default=False)
    excluded_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    admin_score_adjustment: Mapped[float] = mapped_column(Float, default=0.0)
    display_order: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    guest: Mapped[Guest] = relationship("Guest", back_populates="submission")
    score: Mapped[Score | None] = relationship(
        "Score",
        back_populates="submission",
        uselist=False,
        cascade="all, delete-orphan",
    )

    @property
    def image_url(self) -> str:
        name = self.file_path.split("/")[-1]
        return f"/uploads/{name}"


class Score(Base):
    __tablename__ = "scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    submission_id: Mapped[int] = mapped_column(
        ForeignKey("submissions.id", ondelete="CASCADE"),
        unique=True,
    )
    provider: Mapped[str] = mapped_column(String(40))
    model_name: Mapped[str] = mapped_column(String(100))
    total_score: Mapped[float] = mapped_column(Float)
    composition_score: Mapped[float] = mapped_column(Float)
    emotion_score: Mapped[float] = mapped_column(Float)
    story_score: Mapped[float] = mapped_column(Float)
    couple_focus_score: Mapped[float] = mapped_column(Float)
    wedding_mood_score: Mapped[float] = mapped_column(Float)
    summary: Mapped[str] = mapped_column(Text)
    raw_payload: Mapped[str] = mapped_column(Text)
    judged_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    submission: Mapped[Submission] = relationship("Submission", back_populates="score")
