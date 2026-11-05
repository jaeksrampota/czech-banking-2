import hashlib
import logging
import re
import unicodedata
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit

from bs4 import BeautifulSoup, Comment, Tag

from src.collectors.base import BaseCollector, CollectorError
from src.models import Signal

logger = logging.getLogger(__name__)

# The old /hledej/ endpoint returns 404 (2026-11); /prace/ takes the query as q[].
# The locality[]=ceska-republika filter now triggers HTTP 500, so it is not sent.
# www.jobs.cz sometimes redirects to beta.jobs.cz/prace/?keywords[]=..., which serves
# a different layout; both are parsed below.
JOBS_CZ_SEARCH = "https://www.jobs.cz/prace/"
JOBS_CZ_BASE = "https://www.jobs.cz/"

# Per-visit tracking parameters jobs.cz appends to ad links (compared case-insensitively).
# Dropping them keeps the stored URL identical across runs.
TRACKING_PARAMS = {"searchid", "originjobaduuid", "rps", "positionofadinagentemail"}

# Ad detail paths: www.jobs.cz/rpd/<id>/ (classic) and <tenant>.jobs.cz/pd/<id> (beta)
# carry the same numeric ad id.
_JOBS_CZ_AD_PATH = re.compile(r"^/r?pd/(\d+)/?$")
_CANONICAL_AD_URL = re.compile(r"^https://www\.jobs\.cz/rpd/\d+/$")
# Zero-width space/joiners, word joiner and BOM that jobs.cz puts around dashes (written as
# escapes on purpose: the literal characters are invisible in an editor).
_INVISIBLE_CHARS = re.compile("[​-‍⁠﻿]")

# Keywords that indicate strategic significance
HIGH_VALUE_KEYWORDS = {
    "crypto", "blockchain", "defi", "ai", "machine learning", "ml",
    "open banking", "psd2", "psd3", "acquisition", "m&a",
    "digital transformation", "cloud migration", "core banking",
    "generative ai", "llm", "data science",
}

MEDIUM_VALUE_KEYWORDS = {
    "api", "microservices", "data engineer", "devops", "kubernetes",
    "docker", "mobile", "ux", "react", "angular", "python",
    "go", "rust", "kafka", "aws", "azure", "gcp",
}

SENIORITY_HIGH = {"cto", "cio", "ceo", "cfo", "coo", "cdo", "chief",
                   "vp", "vice president", "director", "ředitel", "head of",
                   "vedoucí"}
SENIORITY_MID = {"senior", "lead", "principal", "staff", "architect", "manažer", "manager"}
SENIORITY_LOW = {"junior", "trainee", "intern", "stážista", "graduate"}


def _clean_text(text: str) -> str:
    """Collapse whitespace, turn NBSP into spaces and drop the zero-width joiners jobs.cz puts around dashes."""
    text = _INVISIBLE_CHARS.sub("", text.replace("\xa0", " "))
    return re.sub(r"\s+", " ", text).strip()


def _fold(text: str) -> str:
    """Casefold and strip diacritics, for matching labels such as 'Název firmy'."""
    decomposed = unicodedata.normalize("NFKD", text.casefold())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _has_keyword(text: str, keyword: str) -> bool:
    """Whole-word match, so short keywords ("ai", "go", "ml") do not fire inside "raiffeisenbank" or "logo"."""
    return re.search(rf"(?<!\w){re.escape(keyword)}(?!\w)", text) is not None


def normalize_job_url(url: str, base: str = JOBS_CZ_BASE) -> str:
    """Return a stable URL for a jobs.cz ad.

    Resolves relative links against ``base``, maps both ad-detail flavours
    (www.jobs.cz/rpd/<id>/ and <tenant>.jobs.cz/pd/<id>) to https://www.jobs.cz/rpd/<id>/,
    and otherwise drops tracking parameters, utm_* parameters and the fragment.
    """
    if not url or not url.strip():
        return ""
    parts = urlsplit(urljoin(base, url.strip()))
    host = (parts.hostname or "").lower()
    if host == "jobs.cz" or host.endswith(".jobs.cz"):
        m = _JOBS_CZ_AD_PATH.match(parts.path)
        if m:
            return f"https://www.jobs.cz/rpd/{m.group(1)}/"
    query = [
        (k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in TRACKING_PARAMS and not k.lower().startswith("utm_")
    ]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))


class JobPostingsCollector(BaseCollector):
    name = "job_postings"
    rate_limit_delay = 2.0
    required_source_key = "careers_search_name"

    def collect(self, competitor_id: str) -> list[Signal]:
        config = self._load_competitor_config(competitor_id)
        sources = config.get("sources", {})
        search_name = sources.get("careers_search_name", config["name"])

        signals = []

        # Primary: search jobs.cz
        jobs = self._scrape_jobs_cz(search_name)

        # Also try direct career page if configured
        careers_url = sources.get("careers_url")
        if careers_url:
            try:
                page_jobs = self._scrape_career_page(careers_url, config["name"])
                jobs.extend(page_jobs)
            except CollectorError:
                logger.warning("Failed to scrape career page: %s", careers_url)

        # Deduplicate by title and by (normalised) URL
        seen_titles = set()
        seen_urls = set()
        for job in jobs:
            title_key = job["title"].lower().strip()
            url = job.get("url", "")
            if title_key in seen_titles or (url and url in seen_urls):
                continue
            seen_titles.add(title_key)
            if url:
                seen_urls.add(url)

            score, tags = self._analyze_job(job)
            signal = Signal(
                competitor_id=competitor_id,
                source=self.name,
                signal_type="job_posting",
                title=job["title"],
                content=self._format_job(job),
                url=url,
                severity=score,
                tags=tags,
                metadata=job,
                content_hash=self._job_content_hash(competitor_id, url),
            )
            signals.append(signal)

        return signals

    def _job_content_hash(self, competitor_id: str, url: str) -> str:
        """Dedup key for Database.insert_signal (UNIQUE index on content_hash).

        Signal's default hash covers title + formatted content, which differ between the
        two jobs.cz layouts for the same ad ("Praha – Nusle" vs "Praha-Nusle", salary with
        or without "/měsíc"). A canonical jobs.cz ad URL identifies the ad itself, so it is
        hashed instead. Returns "" (Signal then computes its default) for any other URL.

        Trade-off: one signal per ad. A later edit of the same ad (title, salary, location)
        does not create a new signal; the first seen version is what gets stored.
        """
        if not _CANONICAL_AD_URL.match(url):
            return ""
        raw = f"{competitor_id}|{self.name}|job_posting|{url}"
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _scrape_jobs_cz(self, company_name: str) -> list[dict]:
        try:
            resp = self._fetch(JOBS_CZ_SEARCH, params={"q[]": company_name})
        except CollectorError:
            logger.warning("Failed to search jobs.cz for %s", company_name)
            return []

        # After a redirect to beta.jobs.cz, relative links resolve against the final URL.
        base_url = str(getattr(resp, "url", "") or JOBS_CZ_SEARCH)
        soup = BeautifulSoup(resp.text, "lxml")

        classic_cards = soup.select("article.SearchResultCard")
        beta_cards = soup.select('article[class*="JobCard"]')
        if classic_cards:
            layout, cards, parse = "classic", classic_cards, self._parse_classic_card
        elif beta_cards:
            layout, cards, parse = "beta", beta_cards, self._parse_beta_card
        else:
            logger.warning(
                "jobs.cz markup not recognised for '%s' (%s); no known job cards found",
                company_name, base_url,
            )
            return []

        jobs = [job for job in (parse(card, base_url) for card in cards) if job]
        if not jobs:
            logger.warning(
                "jobs.cz %s layout: %d cards for '%s' but none parsed; selectors may be stale",
                layout, len(cards), company_name,
            )
            return []

        logger.info("Found %d jobs on jobs.cz (%s layout) for '%s'", len(jobs), layout, company_name)
        return jobs

    @staticmethod
    def _job_dict(card: Tag, title: str, company: str, location: str, salary: str, url: str) -> dict:
        return {
            "title": title,
            "company": company,
            "location": location,
            "salary": salary,
            "url": url,
            "full_text": _clean_text(card.get_text(" ", strip=True)).lower(),
        }

    def _parse_classic_card(self, card: Tag, base_url: str) -> dict | None:
        """www.jobs.cz layout: article.SearchResultCard."""
        title_el = card.select_one("h2.SearchResultCard__title a.SearchResultCard__titleLink") or card.select_one(
            "h2 a"
        )
        if not title_el:
            return None
        title = _clean_text(title_el.get_text(" ", strip=True))
        if not title:
            return None
        url = normalize_job_url(title_el.get("href", ""), base_url)

        # Body tags also carry e.g. "Možnost občasné práce z domova"; keep the one with an amount.
        salary = ""
        for tag in card.select(".SearchResultCard__body span.Tag"):
            text = _clean_text(tag.get_text(" ", strip=True))
            if re.search(r"\d", text):
                salary = text
                break

        company = location = ""
        for li in card.select("ul.SearchResultCard__footerList li.SearchResultCard__footerItem"):
            if li.select_one("a[data-test='serp-atmoskop'], a[href*='atmoskop']"):
                continue
            text = _clean_text(li.get_text(" ", strip=True))
            if li.get("data-test") == "serp-locality":
                location = text
            elif not company:
                company = text
            elif not location:
                location = text
        if not company:
            logo = card.select_one(".SearchResultCard__logo img[alt]")
            company = _clean_text(logo["alt"]) if logo else ""

        return self._job_dict(card, title, company, location, salary, url)

    def _parse_beta_card(self, card: Tag, base_url: str) -> dict | None:
        """beta.jobs.cz layout: article.<hash>_JobCard with accessibility-hidden field labels."""
        title_el = card.select_one('h2[class*="JobCardTitle"] a') or card.select_one("h2 a")
        if not title_el:
            return None
        title = _clean_text(title_el.get_text(" ", strip=True))
        if not title:
            return None
        url = normalize_job_url(title_el.get("href", ""), base_url)

        fields: dict[str, str] = {}
        body = card.select_one('div[class*="JobCardBody"]') or card
        for li in body.select("li"):
            if "JobCardFooter" in " ".join(li.get("class", [])):
                continue
            label_el = li.select_one("span.accessibility-hidden")
            if not label_el:
                continue
            label = _fold(_clean_text(label_el.get_text(" ", strip=True))).rstrip(" :")
            value = _clean_text(" ".join(
                str(s) for s in li.find_all(string=True)
                if not isinstance(s, Comment) and label_el not in s.parents
            ))
            if label and value and label not in fields:
                fields[label] = value

        company = fields.get("nazev firmy", "")
        if not company:
            logo = card.select_one('[class*="JobCardLogo"] img[alt]')
            company = _clean_text(logo["alt"]) if logo else ""

        return self._job_dict(
            card, title, company, fields.get("lokalita", ""), fields.get("plat", ""), url
        )

    def _scrape_career_page(self, url: str, company_name: str) -> list[dict]:
        jobs = []
        try:
            resp = self._fetch(url)
        except CollectorError:
            return []

        soup = BeautifulSoup(resp.text, "lxml")
        career_kws = ("pozic", "job", "karier", "vakanc", "nabid")
        for a in soup.select("a[href]"):
            text = a.get_text(strip=True)
            href = a.get("href", "")
            if (
                len(text.split()) >= 2
                and 10 < len(text) < 150
                and any(kw in href.lower() for kw in career_kws)
            ):
                href = urljoin(url, href)
                jobs.append({
                    "title": text,
                    "company": company_name,
                    "url": href,
                    "location": "",
                    "salary": "",
                    "full_text": text.lower(),
                })

        logger.info("Found %d jobs on career page %s", len(jobs), url)
        return jobs

    def _analyze_job(self, job: dict) -> tuple[int, list[str]]:
        text = job.get("full_text", job["title"].lower())
        title_lower = job["title"].lower()
        score = 2
        tags = []

        # Seniority
        if any(kw in title_lower for kw in SENIORITY_HIGH):
            score = max(score, 5)
            tags.append("seniority:executive")
        elif any(kw in title_lower for kw in SENIORITY_MID):
            score = max(score, 3)
            tags.append("seniority:senior")
        elif any(kw in title_lower for kw in SENIORITY_LOW):
            score = 1
            tags.append("seniority:junior")

        # Strategic keywords
        for kw in HIGH_VALUE_KEYWORDS:
            if _has_keyword(text, kw):
                score = max(score, 4)
                tags.append(f"strategic:{kw}")
                break

        # Tech stack
        for kw in MEDIUM_VALUE_KEYWORDS:
            if _has_keyword(text, kw):
                score = max(score, 3)
                tags.append(f"tech:{kw}")

        if job.get("salary"):
            tags.append("has_salary")

        return min(score, 5), tags

    def _format_job(self, job: dict) -> str:
        parts = [job["title"]]
        if job.get("company"):
            parts.append(f"Company: {job['company']}")
        if job.get("location"):
            parts.append(f"Location: {job['location']}")
        if job.get("salary"):
            parts.append(f"Salary: {job['salary']}")
        return " | ".join(parts)
