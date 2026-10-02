from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import (
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


class Post(Base):
    __tablename__ = "posts"

    external_post_id = Column(String, primary_key=True)
    rapper_name = Column(String, nullable=True)
    permalink = Column(String, nullable=False)
    posted_at = Column(DateTime(timezone=True), nullable=False)
    caption = Column(Text, nullable=True)
    media_type = Column(String, nullable=True)
    media_product_type = Column(String, nullable=True)
    classification = Column(String, nullable=False)
    first_seen_at = Column(DateTime(timezone=True), nullable=False)
    last_seen_at = Column(DateTime(timezone=True), nullable=False)


class MetricSnapshot(Base):
    __tablename__ = "metric_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    external_post_id = Column(
        String, ForeignKey("posts.external_post_id"), nullable=False
    )
    fetched_at = Column(DateTime(timezone=True), nullable=False)
    view_count = Column(Integer, nullable=True)
    like_count = Column(Integer, nullable=True)
    comments_count = Column(Integer, nullable=True)

    __table_args__ = (
        UniqueConstraint("external_post_id", "fetched_at", name="uq_snapshot_post_time"),
        Index("ix_snapshot_post_time", "external_post_id", "fetched_at"),
    )


class FetchRun(Base):
    __tablename__ = "fetch_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    started_at = Column(DateTime(timezone=True), nullable=False)
    finished_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(String, nullable=False)  # 'success' | 'partial' | 'error' | 'interrupted'
    posts_seen = Column(Integer, nullable=True)
    new_posts = Column(Integer, nullable=True)
    snapshots_written = Column(Integer, nullable=True)
    api_calls = Column(Integer, nullable=True)
    error_message = Column(Text, nullable=True)


class AccessTokenRecord(Base):
    __tablename__ = "access_tokens"

    id = Column(Integer, primary_key=True, autoincrement=True)
    recorded_at = Column(DateTime(timezone=True), nullable=False)
    token_fingerprint = Column(String, nullable=False)
    token_type = Column(String, nullable=False)  # 'short_lived' | 'long_lived' | 'never_expires'
    issued_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    data_access_expires_at = Column(DateTime(timezone=True), nullable=True)
    scopes = Column(Text, nullable=True)
    source = Column(String, nullable=False)  # 'check' | 'exchange'


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def make_engine(database_url: str):
    if database_url.startswith("sqlite"):
        db_path = database_url.replace("sqlite:///", "")
        if db_path:
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(database_url, future=True)
    Base.metadata.create_all(engine)
    return engine


def make_session_factory(engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, expire_on_commit=False, future=True)
