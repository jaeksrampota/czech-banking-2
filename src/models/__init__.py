import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime


def _utc_now_iso() -> str:
    return datetime.now(UTC).replace(tzinfo=None).isoformat(timespec="seconds")


@dataclass
class Signal:
    competitor_id: str
    source: str
    signal_type: str
    title: str
    content: str = ""
    url: str = ""
    detected_at: str = ""
    published_at: str | None = None
    severity: int = 1
    tags: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    is_new: bool = True
    change_summary: str | None = None
    id: str = ""
    content_hash: str = ""

    def __post_init__(self):
        if not self.id:
            self.id = str(uuid.uuid4())
        if not self.detected_at:
            self.detected_at = _utc_now_iso()
        if not self.content_hash:
            raw = f"{self.competitor_id}|{self.source}|{self.signal_type}|{self.title}|{self.content}"
            self.content_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "competitor_id": self.competitor_id,
            "source": self.source,
            "signal_type": self.signal_type,
            "title": self.title,
            "content": self.content,
            "url": self.url,
            "detected_at": self.detected_at,
            "published_at": self.published_at,
            "severity": self.severity,
            "tags": json.dumps(self.tags, ensure_ascii=False),
            "metadata": json.dumps(self.metadata, ensure_ascii=False),
            "is_new": 1 if self.is_new else 0,
            "change_summary": self.change_summary,
            "content_hash": self.content_hash,
        }
