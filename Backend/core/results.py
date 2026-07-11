from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Optional

STATUSES = {
    "downloaded", "duplicate", "no_new_documents", "exhausted",
    "temporarily_blocked", "site_changed", "invalid_document", "failed",
    "skipped", "manual_review",
}


@dataclass
class CrawlerResult:
    status: str
    reason: str
    source_id: str
    attempted_url: Optional[str] = None
    downloaded_path: Optional[str] = None
    content_hash: Optional[str] = None
    http_status: Optional[int] = None
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    retryable: bool = False
    retry_at: Optional[str] = None
    backoff_class: Optional[str] = None
    timestamp: str = ""

    def __post_init__(self):
        if self.status not in STATUSES:
            raise ValueError(f"Unsupported crawler status: {self.status}")
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self):
        return asdict(self)


def normalize_result(raw: Any, source_id: str) -> CrawlerResult:
    if isinstance(raw, CrawlerResult):
        return raw
    if isinstance(raw, str):
        status = raw if raw in {"downloaded", "skipped", "failed"} else "manual_review"
        return CrawlerResult(status, f"legacy_result:{raw}", source_id, retryable=status == "failed")
    if isinstance(raw, dict):
        data = dict(raw)
        data.setdefault("status", "manual_review")
        data.setdefault("reason", "structured crawler result")
        data.setdefault("source_id", source_id)
        return CrawlerResult(**{k: v for k, v in data.items() if k in CrawlerResult.__dataclass_fields__})
    return CrawlerResult("manual_review", f"unsupported_result_type:{type(raw).__name__}", source_id)
