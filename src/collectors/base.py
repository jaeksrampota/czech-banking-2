import hashlib
import logging
import random
import time
from abc import ABC, abstractmethod
from pathlib import Path

import httpx
import yaml
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from src.alerts import TelegramAlerter
from src.models import Signal
from src.models.database import Database
from src.security.urls import UnsafeURLError, validate_url

logger = logging.getLogger(__name__)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36 Edg/123.0.0.0",
]


class CollectorError(Exception):
    pass


class BaseCollector(ABC):
    name: str = "base"
    rate_limit_delay: float = 2.0
    max_retries: int = 3
    timeout: float = 30.0

    # Each collector declares which config key it requires.
    # If this key is missing from a competitor's sources, that competitor is skipped.
    required_source_key: str | None = None

    def __init__(
        self,
        db: Database,
        config_dir: str,
        alerter: TelegramAlerter | None = None,
    ):
        self.db = db
        self.config_dir = Path(config_dir)
        self._last_request_time: float = 0
        self._client: httpx.Client | None = None
        self.alerter = alerter if alerter is not None else TelegramAlerter()

    def __enter__(self):
        self._client = httpx.Client(timeout=self.timeout, follow_redirects=True)
        return self

    def __exit__(self, *args):
        if self._client:
            self._client.close()
            self._client = None

    @property
    def client(self) -> httpx.Client:
        if self._client is None:
            raise CollectorError("Collector must be used as context manager")
        return self._client

    def _rate_limit(self):
        elapsed = time.time() - self._last_request_time
        if elapsed < self.rate_limit_delay:
            time.sleep(self.rate_limit_delay - elapsed)
        self._last_request_time = time.time()

    def _get_headers(self) -> dict:
        return {
            "User-Agent": random.choice(USER_AGENTS),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "cs,en;q=0.5",
        }

    def _fetch(self, url: str, **kwargs) -> httpx.Response:
        try:
            validate_url(url)
        except UnsafeURLError as e:
            logger.warning("Refusing to fetch unsafe URL %s: %s", url, e)
            raise CollectorError(str(e)) from e

        self._rate_limit()
        headers = self._get_headers()
        headers.update(kwargs.pop("headers", {}))

        @retry(
            stop=stop_after_attempt(self.max_retries),
            wait=wait_exponential(multiplier=1, min=2, max=30),
            retry=retry_if_exception_type((httpx.TransportError, httpx.TimeoutException)),
            reraise=True,
        )
        def _do_fetch():
            resp = self.client.get(url, headers=headers, **kwargs)
            resp.raise_for_status()
            return resp

        try:
            return _do_fetch()
        except Exception as e:
            logger.error("Failed to fetch %s: %s", url, e)
            raise CollectorError(f"Failed to fetch {url}: {e}") from e

    def _fetch_and_store_snapshot(
        self, competitor_id: str, snapshot_key: str, url: str, **kwargs
    ) -> tuple[str, bool]:
        resp = self._fetch(url, **kwargs)
        content = resp.text
        content_hash = hashlib.sha256(content.encode("utf-8")).hexdigest()

        prev = self.db.get_latest_snapshot(competitor_id, self.name, snapshot_key)
        has_changed = prev is None or prev["content_hash"] != content_hash

        if has_changed:
            self.db.insert_snapshot(
                competitor_id, self.name, snapshot_key, content, content_hash
            )

        return content, has_changed

    def _load_competitor_config(self, competitor_id: str) -> dict:
        config_path = self.config_dir / "competitors" / f"{competitor_id}.yaml"
        if not config_path.exists():
            raise CollectorError(f"No config for {competitor_id}")
        return yaml.safe_load(config_path.read_text(encoding="utf-8"))

    def _get_applicable_competitors(self) -> list[str]:
        competitors = self.db.get_competitors()
        applicable = []
        for comp in competitors:
            config = self._load_competitor_config(comp["id"])
            sources = config.get("sources", {})
            if self.required_source_key is None or self.required_source_key in sources:
                applicable.append(comp["id"])
        return applicable

    @abstractmethod
    def collect(self, competitor_id: str) -> list[Signal]:
        ...

    def run(self, competitor_ids: list[str] | None = None) -> dict:
        if competitor_ids is None:
            competitor_ids = self._get_applicable_competitors()

        results = {"total": 0, "new_signals": 0, "errors": 0, "competitors": {}}

        for cid in competitor_ids:
            run_id = self.db.start_collector_run(self.name, cid)
            try:
                signals = self.collect(cid)
                new_count = 0
                newly_inserted: list[Signal] = []
                for sig in signals:
                    if self.db.insert_signal(sig.to_dict()):
                        new_count += 1
                        newly_inserted.append(sig)
                self.db.finish_collector_run(run_id, "success", new_count)
                results["new_signals"] += new_count
                results["competitors"][cid] = {"status": "success", "signals": new_count}
                logger.info("[%s] %s: %d new signals", self.name, cid, new_count)
                if self.alerter.enabled and newly_inserted:
                    alerted = self.alerter.send_signals(newly_inserted)
                    if alerted:
                        logger.info("[%s] %s: alerted on %d signals", self.name, cid, alerted)
            except Exception as e:
                self.db.finish_collector_run(run_id, "failed", error_message=str(e))
                results["errors"] += 1
                results["competitors"][cid] = {"status": "failed", "error": str(e)}
                logger.exception("[%s] %s failed: %s", self.name, cid, e)

        results["total"] = len(competitor_ids)
        return results
