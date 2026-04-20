import contextlib
import logging

import feedparser
import yaml
from bs4 import BeautifulSoup
from dateutil.parser import parse as parse_date

from src.collectors.base import BaseCollector, CollectorError
from src.models import Signal

logger = logging.getLogger(__name__)

HIGH_KEYWORDS = {
    "akvizice", "acquisition", "fúze", "merger", "regulat",
    "pokuta", "fine", "penalty", "sankce", "licence",
    "ipo", "transformace", "restrukturalizace", "restructur",
    "ceo", "ředitel", "jmenování", "odvolání", "resignation",
    "čnb", "cnb", "úroková sazba", "interest rate",
}
MEDIUM_KEYWORDS = {
    "nový produkt", "new product", "spouští", "launch",
    "partnerství", "partnership", "spolupráce", "cooperation",
    "investice", "investment", "expanze", "expansion",
    "digitální", "digital", "inovace", "innovation",
    "hypotéka", "mortgage", "úvěr", "kredit",
}
CATEGORY_MAP = {
    "regulation": ["regulat", "pokuta", "fine", "sankce", "licence", "čnb", "cnb", "dohled"],
    "m&a": ["akvizice", "fúze", "merger", "acquisition"],
    "leadership": ["ceo", "ředitel", "jmenování", "odvolání", "board", "představenstvo"],
    "product": ["nový produkt", "spouští", "launch", "aplikace", "app", "mobilní"],
    "partnership": ["partnerství", "partnership", "spolupráce"],
    "financial": ["zisk", "profit", "ztráta", "loss", "výsledky", "results", "tržby", "revenue"],
    "rates": ["úroková sazba", "interest rate", "sazby", "hypotéka", "mortgage"],
}


class NewsCollector(BaseCollector):
    name = "news"
    rate_limit_delay = 1.0
    # No required_source_key — this collector always runs (industry feeds apply to all)
    required_source_key = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._industry_feeds: list[dict] | None = None
        self._alias_map: dict[str, list[str]] | None = None

    def _load_industry_feeds(self) -> list[dict]:
        if self._industry_feeds is not None:
            return self._industry_feeds
        sources_path = self.config_dir / "sources.yaml"
        if not sources_path.exists():
            logger.warning("No sources.yaml found at %s", sources_path)
            self._industry_feeds = []
            return self._industry_feeds
        data = yaml.safe_load(sources_path.read_text(encoding="utf-8"))
        self._industry_feeds = data.get("industry_feeds", [])
        logger.info("Loaded %d industry feeds", len(self._industry_feeds))
        return self._industry_feeds

    def _load_alias_map(self) -> dict[str, list[str]]:
        """Build a map of competitor_id -> list of lowercase aliases."""
        if self._alias_map is not None:
            return self._alias_map
        self._alias_map = {}
        competitors = self.db.get_competitors()
        for comp in competitors:
            config = self._load_competitor_config(comp["id"])
            aliases = config.get("aliases", [])
            # Always include the name itself
            all_names = set(a.lower() for a in aliases)
            all_names.add(comp["name"].lower())
            self._alias_map[comp["id"]] = list(all_names)
        return self._alias_map

    def _match_competitors(self, text: str) -> list[str]:
        """Find which competitors are mentioned in text."""
        text_lower = text.lower()
        alias_map = self._load_alias_map()
        matched = []
        for comp_id, aliases in alias_map.items():
            for alias in aliases:
                if alias in text_lower:
                    matched.append(comp_id)
                    break
        return matched

    def collect(self, competitor_id: str) -> list[Signal]:
        config = self._load_competitor_config(competitor_id)
        sources = config.get("sources", {})
        signals = []

        # 1. Competitor-specific Google News RSS
        rss_url = sources.get("news_rss")
        if rss_url:
            signals.extend(self._collect_feed(
                competitor_id, rss_url, "google_news",
            ))

        # 2. Industry-wide feeds — only collect articles mentioning this competitor
        for feed in self._load_industry_feeds():
            feed_signals = self._collect_feed(
                competitor_id=None,  # will be matched
                rss_url=feed["url"],
                feed_name=feed["name"],
                feed_category=feed.get("category", ""),
                feed_priority=feed.get("priority", "medium"),
            )
            for sig in feed_signals:
                # Match to this specific competitor
                text = f"{sig.title} {sig.content}"
                if competitor_id in self._match_competitors(text):
                    sig.competitor_id = competitor_id
                    signals.append(sig)

        return signals

    def _collect_feed(
        self,
        competitor_id: str | None,
        rss_url: str,
        feed_name: str,
        feed_category: str = "",
        feed_priority: str = "medium",
    ) -> list[Signal]:
        signals = []

        try:
            resp = self._fetch(rss_url)
        except CollectorError:
            logger.warning("Failed to fetch RSS: %s (%s)", feed_name, rss_url)
            return []

        feed = feedparser.parse(resp.text)

        for entry in feed.entries:
            title = entry.get("title", "").strip()
            link = entry.get("link", "")
            published = entry.get("published", "")
            summary = entry.get("summary", "")

            if not title:
                continue

            if summary:
                summary = BeautifulSoup(summary, "lxml").get_text(strip=True)

            published_at = None
            if published:
                with contextlib.suppress(ValueError, TypeError):
                    published_at = parse_date(published).isoformat()

            score, tags = self._analyze_article(title, summary)

            # Boost score for critical/high-priority feeds
            if feed_priority == "critical" and score < 4:
                score = min(score + 1, 5)

            # Add feed source tag
            if feed_category:
                tags.append(f"feed:{feed_category}")
            tags.append(f"src:{feed_name}")

            signal = Signal(
                competitor_id=competitor_id or "__unmatched__",
                source=self.name,
                signal_type="news_article",
                title=title,
                content=summary[:1000] if summary else title,
                url=link,
                published_at=published_at,
                severity=score,
                tags=tags,
                metadata={
                    "feed_name": feed_name,
                    "feed_url": rss_url,
                    "feed_category": feed_category,
                    "published_raw": published,
                },
            )
            signals.append(signal)

        logger.info("Found %d articles from %s", len(signals), feed_name)
        return signals

    def _analyze_article(self, title: str, summary: str) -> tuple[int, list[str]]:
        text = f"{title} {summary}".lower()
        tags = ["news"]

        if any(kw in text for kw in HIGH_KEYWORDS):
            score = 4
        elif any(kw in text for kw in MEDIUM_KEYWORDS):
            score = 3
        else:
            score = 2

        for category, keywords in CATEGORY_MAP.items():
            if any(kw in text for kw in keywords):
                tags.append(category)

        return score, tags
