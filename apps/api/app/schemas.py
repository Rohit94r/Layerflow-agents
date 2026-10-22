"""Request bodies. Responses are plain dicts built in app/serializers.py (one place that defines the wire shape)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, HttpUrl, field_validator

Category = Literal["brief", "thinking", "room", "playbook", "decisions", "deep_dive"]
Region = Literal["global", "us", "eu", "uk", "india", "mena", "apac", "africa", "latam"]
SourceKind = Literal["rss", "gdelt", "edgar", "ir", "hn", "reddit", "manual"]
Stage = Literal["research", "write", "edit", "seo", "qa"]
PublishTarget = Literal["export", "ten_static", "wordpress", "webhook"]


class Body(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class LoginIn(Body):
    email: EmailStr
    password: str = Field(min_length=1, max_length=512)


# ---- discovery ----
class FeedRefreshIn(Body):
    source_id: str | None = None


class PromoteIn(Body):
    category: Category | None = None
    angle: str | None = Field(default=None, max_length=500)
    auto: bool = True


class BulkPromoteIn(Body):
    ids: list[str] = Field(min_length=1, max_length=50)
    auto: bool = True


class IgnoreIn(Body):
    reason: str = Field(default="Not relevant", max_length=500)


class SourceIn(Body):
    kind: SourceKind
    name: str = Field(min_length=2, max_length=200)
    url: HttpUrl
    weight: float = Field(default=1.0, ge=0.1, le=2.0)
    region: Region | None = None
    active: bool = True


class SourcePatch(Body):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    url: HttpUrl | None = None
    kind: SourceKind | None = None
    weight: float | None = Field(default=None, ge=0.1, le=2.0)
    region: Region | None = None
    active: bool | None = None


# ---- topics & articles ----
class TopicIn(Body):
    title: str = Field(min_length=8, max_length=300)
    category: Category
    angle: str | None = Field(default=None, max_length=500)
    region: Region | None = None
    notes: str | None = Field(default=None, max_length=20000)
    links: list[HttpUrl] = Field(default_factory=list, max_length=10)
    auto: bool = True


class RunStageIn(Body):
    stage: Literal["research", "write", "edit", "seo", "qa", "auto"]


class ReviseIn(Body):
    stage: Literal["write", "edit", "seo"]
    instruction: str = Field(min_length=3, max_length=2000)


class SectionIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    key: str
    heading: str = Field(max_length=160)
    paragraphs: list[str] = Field(default_factory=list)
    bullets: list[str] = Field(default_factory=list)
    pull_quote: str | None = None
    facts_used: list[int] = Field(default_factory=list)


class ArticlePatch(Body):
    title: str | None = Field(default=None, min_length=10, max_length=120)
    dek: str | None = Field(default=None, max_length=300)
    sections: list[SectionIn] | None = None
    takeaway: str | None = Field(default=None, max_length=600)
    note: str | None = Field(default=None, max_length=300)


class ReviewIn(Body):
    note: str | None = Field(default=None, max_length=2000)


class RejectIn(Body):
    reason: str = Field(min_length=3, max_length=2000)


class RequestRevisionIn(Body):
    reason: str = Field(min_length=3, max_length=2000)
    stage: Literal["write", "edit"] = "write"


class ForceReviewIn(Body):
    reason: str = Field(min_length=10, max_length=2000)


# ---- seo ----
class SeoPatch(Body):
    title_tag: str | None = Field(default=None, max_length=90)
    meta_description: str | None = Field(default=None, max_length=200)
    slug: str | None = Field(default=None, max_length=80)
    primary_keyword: str | None = Field(default=None, max_length=80)
    secondary_keywords: list[str] | None = None
    canonical_url: str | None = Field(default=None, max_length=300)
    h1: str | None = Field(default=None, max_length=120)


# ---- publications ----
class PublicationIn(Body):
    article_id: str
    target: PublishTarget | None = None
    scheduled_at: datetime | None = None  # null = next cadence slot


class DryRunIn(Body):
    article_id: str
    target: PublishTarget | None = None


class PublicationPatch(Body):
    scheduled_at: datetime | None = None
    status: Literal["cancelled"] | None = None


# ---- social ----
class SocialPatch(Body):
    text: str | None = Field(default=None, min_length=20, max_length=3000)
    hashtags: list[str] | None = Field(default=None, max_length=3)
    image_url: str | None = Field(default=None, max_length=500)
    status: Literal["draft_ready", "approved"] | None = None

    @field_validator("hashtags")
    @classmethod
    def _tags(cls, v: list[str] | None) -> list[str] | None:
        if v is None:
            return v
        out = []
        for tag in v:
            tag = tag.strip().lstrip("#")
            if not tag or not tag.replace("_", "").isalnum():
                raise ValueError(f"Invalid hashtag '{tag}'")
            out.append(tag)
        return out


# ---- settings ----
class TenantPatch(Body):
    name: str | None = Field(default=None, min_length=2, max_length=200)
    domain: str | None = Field(default=None, max_length=200)
    timezone: str | None = Field(default=None, max_length=64)
    settings: dict[str, Any] | None = None


class PromptPut(Body):
    body: str = Field(min_length=20, max_length=60000)
    note: str | None = Field(default=None, max_length=300)


class PromptActivate(Body):
    version_id: str


class PersonaPut(Body):
    persona: str | None = Field(default=None, min_length=20, max_length=60000)
    banned_phrases: list[str] | None = Field(default=None, max_length=500)
    note: str | None = Field(default=None, max_length=300)


class AgentModelConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    model: str | None = Field(default=None, max_length=200)
    temperature: float | None = Field(default=None, ge=0, le=1.5)
    num_ctx: int | None = Field(default=None, ge=1024, le=131072)
    max_tokens: int | None = Field(default=None, ge=32, le=16384)


class ModelsIn(Body):
    agents: dict[str, AgentModelConfig] = Field(default_factory=dict)


class ModelTestIn(Body):
    model: str | None = None


class IntegrationsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    default_target: PublishTarget | None = None
    ten_static: dict[str, Any] | None = None
    wordpress: dict[str, Any] | None = None
    webhook: dict[str, Any] | None = None
    linkedin: dict[str, Any] | None = None


class IntegrationTestIn(Body):
    target: Literal["export", "ten_static", "wordpress", "webhook", "linkedin"]


class EvalRunIn(Body):
    suite: Literal["critic", "pipeline", "deterministic"] = "critic"
    case_ids: list[str] | None = None


class MaintenanceIn(Body):
    older_than_days: int | None = Field(default=None, ge=1, le=3650)
    confirm: str = Field(min_length=3, max_length=64)
