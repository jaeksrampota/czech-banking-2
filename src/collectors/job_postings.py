import logging
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from src.collectors.base import BaseCollector, CollectorError
from src.models import Signal

logger = logging.getLogger(__name__)

JOBS_CZ_SEARCH = "https://www.jobs.cz/hledej/"

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

        # Deduplicate by title
        seen_titles = set()
        for job in jobs:
            title_key = job["title"].lower().strip()
            if title_key in seen_titles:
                continue
            seen_titles.add(title_key)

            score, tags = self._analyze_job(job)
            signal = Signal(
                competitor_id=competitor_id,
                source=self.name,
                signal_type="job_posting",
                title=job["title"],
                content=self._format_job(job),
                url=job.get("url", ""),
                severity=score,
                tags=tags,
                metadata=job,
            )
            signals.append(signal)

        return signals

    def _scrape_jobs_cz(self, company_name: str) -> list[dict]:
        jobs = []
        try:
            resp = self._fetch(
                JOBS_CZ_SEARCH,
                params={"q": company_name, "locality[]": "ceska-republika"},
            )
        except CollectorError:
            logger.warning("Failed to search jobs.cz for %s", company_name)
            return []

        soup = BeautifulSoup(resp.text, "lxml")

        for card in soup.select("article, div.standalone-search-item, div[data-jobad-id]"):
            title_el = card.select_one("h2 a, h3 a, a.search-list__main-info__title")
            if not title_el:
                continue

            title = title_el.get_text(strip=True)
            url = title_el.get("href", "")
            if url:
                url = urljoin("https://www.jobs.cz/", url)

            company_el = card.select_one(".company-name, span.search-list__main-info__company")
            company = company_el.get_text(strip=True) if company_el else ""

            location_el = card.select_one(".location, span.search-list__main-info__address")
            location = location_el.get_text(strip=True) if location_el else ""

            salary_el = card.select_one(".salary, span.search-list__main-info__salary")
            salary = salary_el.get_text(strip=True) if salary_el else ""

            full_text = card.get_text(" ", strip=True).lower()

            jobs.append({
                "title": title,
                "company": company,
                "location": location,
                "salary": salary,
                "url": url,
                "full_text": full_text,
            })

        logger.info("Found %d jobs on jobs.cz for '%s'", len(jobs), company_name)
        return jobs

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
            if kw in text:
                score = max(score, 4)
                tags.append(f"strategic:{kw}")
                break

        # Tech stack
        for kw in MEDIUM_VALUE_KEYWORDS:
            if kw in text:
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
