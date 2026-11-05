"""jobs.cz collector tests. All HTTP is stubbed; fixtures are trimmed captures of the live
www.jobs.cz (classic) and beta.jobs.cz search pages taken on 2026-11-05."""

import logging
from pathlib import Path

import httpx
import pytest
from src.collectors.base import CollectorError
from src.collectors.job_postings import JOBS_CZ_SEARCH, JobPostingsCollector, normalize_job_url

FIXTURES = Path(__file__).parent / "fixtures"
CLASSIC_URL = "https://www.jobs.cz/prace/?q%5B%5D=Raiffeisenbank"
BETA_URL = "https://beta.jobs.cz/prace/?keywords%5B%5D=Raiffeisenbank"


def _collector_serving(html: str, final_url: str, calls: list | None = None) -> JobPostingsCollector:
    """A collector whose _fetch returns ``html`` as if the request ended at ``final_url``."""
    collector = JobPostingsCollector.__new__(JobPostingsCollector)

    def fake_fetch(url, **kwargs):
        if calls is not None:
            calls.append((url, kwargs))
        return httpx.Response(200, text=html, request=httpx.Request("GET", final_url))

    collector._fetch = fake_fetch
    return collector


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def test_classic_layout_parses_cards_and_uses_new_endpoint():
    calls: list = []
    collector = _collector_serving(_fixture("jobs_cz_classic.html"), CLASSIC_URL, calls)

    jobs = collector._scrape_jobs_cz("Raiffeisenbank")

    assert calls == [(JOBS_CZ_SEARCH, {"params": {"q[]": "Raiffeisenbank"}})]
    assert JOBS_CZ_SEARCH == "https://www.jobs.cz/prace/"
    assert [(j["title"], j["company"], j["location"], j["salary"], j["url"]) for j in jobs] == [
        ("Bankéř*ka - Praha, Bělehradská", "Raiffeisenbank a.s.", "Praha",
         "40 000 – 55 000 Kč", "https://www.jobs.cz/rpd/2001495462/"),
        ("DevOps Engineer – Digital Banking (m/f)", "Raiffeisenbank a.s.", "Praha – Nusle",
         "", "https://www.jobs.cz/rpd/2001491782/"),
        ("Bankéř*ka - Praha, Vodičkova", "Raiffeisenbank a.s.", "Praha",
         "40 000 – 55 000 Kč", "https://www.jobs.cz/rpd/2001517717/"),
    ]
    for job in jobs:
        assert set(job) == {"title", "company", "location", "salary", "url", "full_text"}
        assert "atmoskop" not in job["company"].lower()
        assert "atmoskop" not in job["location"].lower()
        assert "‍" not in job["full_text"]


def test_beta_layout_parses_hashed_class_cards():
    collector = _collector_serving(_fixture("jobs_cz_beta.html"), BETA_URL)

    jobs = collector._scrape_jobs_cz("Raiffeisenbank")

    assert [(j["title"], j["company"], j["location"], j["salary"], j["url"]) for j in jobs] == [
        ("Bankéř*ka - Praha, Vodičkova", "Raiffeisenbank a.s.", "Praha",
         "40 000 – 55 000 Kč/měsíc", "https://www.jobs.cz/rpd/2001517717/"),
        ("AML Governance Expert*ka", "Raiffeisenbank a.s.", "Praha",
         "", "https://www.jobs.cz/rpd/2001516759/"),
        # Relative link on the beta page resolves against the final (redirected) URL.
        ("MISTR LAKOVNY (52 000 Kč až 65 000 Kč)", "Hitachi Energy Czech Republic s.r.o.", "Brno-Slatina",
         "52 000 – 65 000 Kč/měsíc",
         "https://beta.jobs.cz/firma/p9y6a1-hitachi-energy-czech-republic-s-r-o/nabidka/"
         "882a586b-f135-4c5e-b8d3-7dbbd7327fc9/"),
    ]
    for job in jobs:
        assert "aktualizováno" not in job["company"].lower()
        assert "plat" not in job["salary"].lower()
        assert "lokalita" not in job["location"].lower()


def test_same_ad_gets_same_url_and_dedup_hash_in_both_layouts(seeded_db, tmp_config_dir):
    for path, final_url in (("jobs_cz_classic.html", CLASSIC_URL), ("jobs_cz_beta.html", BETA_URL)):
        collector = _collector_serving(_fixture(path), final_url)
        collector.config_dir = tmp_config_dir
        signals = collector.collect("acme_bank")
        vodickova = next(s for s in signals if s.title == "Bankéř*ka - Praha, Vodičkova")
        assert vodickova.url == "https://www.jobs.cz/rpd/2001517717/"
        assert vodickova.metadata["url"] == vodickova.url
        inserted = [seeded_db.insert_signal(s.to_dict()) for s in signals]
        if path == "jobs_cz_classic.html":
            assert all(inserted)
        else:
            # Vodičkova was already stored from the classic page even though location and
            # salary text differ between layouts; AML Governance and Hitachi are new.
            assert inserted == [False, True, True]

    urls = [s["url"] for s in seeded_db.get_signals(source="job_postings", limit=100)]
    assert urls.count("https://www.jobs.cz/rpd/2001517717/") == 1


def test_rerun_of_same_page_inserts_nothing(seeded_db, tmp_config_dir):
    collector = _collector_serving(_fixture("jobs_cz_classic.html"), CLASSIC_URL)
    collector.config_dir = tmp_config_dir
    first = [seeded_db.insert_signal(s.to_dict()) for s in collector.collect("acme_bank")]
    second = [seeded_db.insert_signal(s.to_dict()) for s in collector.collect("acme_bank")]
    assert all(first) and len(first) == 3
    assert not any(second)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://www.jobs.cz/rpd/2001495462/?searchId=05decd6e-98f8-4b57-971c-58f9b8510f78&rps=228",
         "https://www.jobs.cz/rpd/2001495462/"),
        ("https://rb.jobs.cz/pd/2001517717?originJobAdUuid=d0c7d8a5-72ff-45df-acb4-d6a5a588b370&rps=2233",
         "https://www.jobs.cz/rpd/2001517717/"),
        ("/rpd/2001491782/?searchId=abc#top", "https://www.jobs.cz/rpd/2001491782/"),
        ("https://beta.jobs.cz/firma/x/nabidka/882a/?rps=2233&utm_source=jobs&page=2",
         "https://beta.jobs.cz/firma/x/nabidka/882a/?page=2"),
        ("", ""),
    ],
)
def test_normalize_job_url_strips_tracking(raw, expected):
    assert normalize_job_url(raw) == expected


def test_unknown_markup_returns_empty_with_warning(caplog):
    html = "<html><body><article class='SomethingNew'><h2><a href='/x'>Job</a></h2></article></body></html>"
    collector = _collector_serving(html, CLASSIC_URL)
    with caplog.at_level(logging.WARNING, logger="src.collectors.job_postings"):
        assert collector._scrape_jobs_cz("Raiffeisenbank") == []
    assert any("not recognised" in r.getMessage() for r in caplog.records)


def test_fetch_failure_returns_empty(caplog):
    collector = JobPostingsCollector.__new__(JobPostingsCollector)

    def boom(url, **kwargs):
        raise CollectorError("HTTP 500")

    collector._fetch = boom
    with caplog.at_level(logging.WARNING, logger="src.collectors.job_postings"):
        assert collector._scrape_jobs_cz("Raiffeisenbank") == []
    assert caplog.records


def test_analyze_job_scoring_and_tags():
    collector = JobPostingsCollector.__new__(JobPostingsCollector)
    jobs = {j["title"]: j for j in _collector_serving(
        _fixture("jobs_cz_classic.html"), CLASSIC_URL
    )._scrape_jobs_cz("Raiffeisenbank")}

    # "raiffeisenbank" in every card must not trigger the "ai" keyword.
    score, tags = collector._analyze_job(jobs["Bankéř*ka - Praha, Bělehradská"])
    assert (score, tags) == (2, ["has_salary"])

    score, tags = collector._analyze_job(jobs["DevOps Engineer – Digital Banking (m/f)"])
    assert score == 3
    assert tags == ["tech:devops"]

    score, tags = collector._analyze_job({
        "title": "Ředitel*ka pobočky Příbram",
        "full_text": "ředitel*ka pobočky příbram generative ai python",
        "salary": "55 000 – 95 000 Kč",
    })
    assert score == 5
    assert tags[0] == "seniority:executive"
    assert any(t.startswith("strategic:") for t in tags)
    assert "tech:python" in tags
    assert tags[-1] == "has_salary"

    score, tags = collector._analyze_job({"title": "Junior analytik", "full_text": "junior analytik"})
    assert (score, tags) == (1, ["seniority:junior"])
