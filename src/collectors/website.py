"""Website collector — fetch URLs listed in each competitor's YAML config
(website_urls, pricing_url, careers_url) and extract heading+link pairs
as research seed signals.

The goal is not deep scraping — it's a broad sweep that turns the
configured URLs into a catalogue of "discovered links" per competitor
that a human can then triage / articlize.
"""
import logging
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from src.collectors.base import BaseCollector, CollectorError
from src.models import Signal

logger = logging.getLogger(__name__)

# Minimum text length for a link to be interesting
MIN_LINK_TEXT = 15
MAX_LINK_TEXT = 180
MAX_LINKS_PER_PAGE = 40

# Noise patterns — skip nav, cookies, legal, social
NOISE_PATTERNS = re.compile(
    r"(cookie|gdpr|souhlas|zásady|podmínky|terms|privacy|impressum|"
    r"facebook\.com|instagram\.com|twitter\.com|linkedin\.com|youtube\.com|x\.com|"
    r"^#|javascript:|mailto:|tel:)",
    re.IGNORECASE,
)

# Category hints
CATEGORY_KEYWORDS = {
    "news":     ["zpráv", "novin", "tisko", "blog", "aktuali", "press"],
    "product":  ["produkt", "účet", "karta", "hypot", "úvěr", "pojišt", "fond",
                 "spoření", "investic", "půjč"],
    "pricing":  ["sazebn", "ceník", "cen", "poplat", "tarif", "pricing"],
    "careers":  ["kariér", "kariera", "pracov", "nábor", "job", "volná pozice"],
    "support":  ["kontakt", "podpor", "pomoc", "help", "faq"],
}

# Page types from YAML
PAGE_TYPE_LABELS = {
    "website":  "web",
    "pricing":  "ceník",
    "careers":  "kariéra",
}


class WebsiteCollector(BaseCollector):
    name = "website"
    rate_limit_delay = 2.0
    # No single required key — overridden below
    required_source_key = None

    def _get_applicable_competitors(self) -> list[str]:
        """Competitor is applicable if it has any of website_urls / pricing_url / careers_url."""
        applicable = []
        for comp in self.db.get_competitors():
            try:
                config = self._load_competitor_config(comp["id"])
            except CollectorError:
                continue
            sources = config.get("sources", {})
            if (sources.get("website_urls") or sources.get("pricing_url")
                    or sources.get("careers_url")):
                applicable.append(comp["id"])
        return applicable

    def collect(self, competitor_id: str) -> list[Signal]:
        config = self._load_competitor_config(competitor_id)
        sources = config.get("sources", {})

        targets: list[tuple[str, str]] = []
        for u in sources.get("website_urls", []) or []:
            targets.append((u, "website"))
        if sources.get("pricing_url"):
            targets.append((sources["pricing_url"], "pricing"))
        if sources.get("careers_url"):
            targets.append((sources["careers_url"], "careers"))

        signals: list[Signal] = []
        for url, page_type in targets:
            signals.extend(self._scrape_page(competitor_id, url, page_type))
        return signals

    # ── Scraping ─────────────────────────────────────────────────

    def _scrape_page(
        self, competitor_id: str, url: str, page_type: str,
    ) -> list[Signal]:
        snapshot_key = f"{page_type}:{url}"
        try:
            content, has_changed = self._fetch_and_store_snapshot(
                competitor_id, snapshot_key, url,
            )
        except CollectorError as e:
            logger.warning("Failed to fetch %s: %s", url, e)
            return []

        if not has_changed:
            logger.info("No change on %s (%s)", url, competitor_id)
            return []

        soup = BeautifulSoup(content, "lxml")

        signals: list[Signal] = []

        # 1) Baseline signal — page title + meta description
        title_text = self._page_title(soup)
        desc_text = self._meta_description(soup)
        signals.append(Signal(
            competitor_id=competitor_id,
            source=self.name,
            signal_type=f"website_{page_type}",
            title=f"{PAGE_TYPE_LABELS.get(page_type, page_type)}: {title_text}",
            content=desc_text or title_text,
            url=url,
            severity=2,
            tags=[page_type, "baseline"],
            metadata={"page_type": page_type, "source_url": url},
        ))

        # 2) Extracted links
        link_signals = self._extract_link_signals(
            soup, competitor_id, url, page_type,
        )
        signals.extend(link_signals)

        logger.info(
            "[%s] %s (%s): baseline + %d discovered links",
            competitor_id, url, page_type, len(link_signals),
        )
        return signals

    def _page_title(self, soup: BeautifulSoup) -> str:
        if soup.title and soup.title.string:
            return soup.title.string.strip()[:200]
        h1 = soup.find("h1")
        if h1:
            return h1.get_text(strip=True)[:200]
        return "Bez titulku"

    def _meta_description(self, soup: BeautifulSoup) -> str:
        for sel in [
            ('meta', {'name': 'description'}),
            ('meta', {'property': 'og:description'}),
        ]:
            el = soup.find(*sel)
            if el and el.get("content"):
                return el["content"].strip()[:500]
        return ""

    def _extract_link_signals(
        self, soup: BeautifulSoup, competitor_id: str, base_url: str, page_type: str,
    ) -> list[Signal]:
        base_domain = urlparse(base_url).netloc

        # Strip script/style/nav/footer
        for tag in soup(["script", "style", "noscript"]):
            tag.decompose()

        seen_hrefs: set[str] = set()
        signals: list[Signal] = []

        for a in soup.find_all("a", href=True):
            href = a.get("href", "").strip()
            text = a.get_text(" ", strip=True)

            if not href or NOISE_PATTERNS.search(href):
                continue
            if not text or len(text) < MIN_LINK_TEXT or len(text) > MAX_LINK_TEXT:
                continue

            # Resolve + dedupe
            full_url = urljoin(base_url, href)
            parsed = urlparse(full_url)
            if parsed.scheme not in ("http", "https"):
                continue

            # Keep only links inside the same domain (in-scope)
            if parsed.netloc and parsed.netloc != base_domain:
                # Keep different subdomain if it's the same root
                root = ".".join(base_domain.split(".")[-2:])
                if root not in parsed.netloc:
                    continue

            if full_url in seen_hrefs:
                continue
            seen_hrefs.add(full_url)

            category, severity = self._classify_link(text, full_url, page_type)
            tags = [page_type, f"category:{category}"]

            signals.append(Signal(
                competitor_id=competitor_id,
                source=self.name,
                signal_type=f"link_{category}",
                title=text,
                content=f"Nalezeno na {base_url}",
                url=full_url,
                severity=severity,
                tags=tags,
                metadata={
                    "discovered_on": base_url,
                    "page_type": page_type,
                    "category": category,
                },
            ))

            if len(signals) >= MAX_LINKS_PER_PAGE:
                break

        return signals

    def _classify_link(
        self, text: str, url: str, page_type: str,
    ) -> tuple[str, int]:
        """Guess a category + severity for a discovered link."""
        haystack = f"{text} {url}".lower()
        for cat, keywords in CATEGORY_KEYWORDS.items():
            if any(k in haystack for k in keywords):
                # Severity — news/product are more interesting than support
                sev = {
                    "news":    3,
                    "product": 3,
                    "pricing": 3,
                    "careers": 2,
                    "support": 1,
                }.get(cat, 2)
                return cat, sev
        # Fallback by page_type
        return page_type, 2
