from src.collectors.ares import AresCollector
from src.collectors.job_postings import JobPostingsCollector
from src.collectors.news import NewsCollector


def test_ares_classify_board_change():
    sig_type, sev = AresCollector._classify_ares_change(
        AresCollector.__new__(AresCollector), "statutarniOrgan.clenove[0]"
    )
    assert sig_type == "board_change"
    assert sev == 4


def test_ares_classify_capital_change():
    sig_type, sev = AresCollector._classify_ares_change(
        AresCollector.__new__(AresCollector), "zakladniKapital"
    )
    assert sig_type == "capital_change"
    assert sev == 4


def test_jobs_analyzer_flags_executive_seniority():
    collector = JobPostingsCollector.__new__(JobPostingsCollector)
    score, tags = collector._analyze_job({
        "title": "CTO",
        "full_text": "cto cloud migration",
    })
    assert score == 5
    assert "seniority:executive" in tags


def test_jobs_analyzer_boosts_strategic_keyword():
    collector = JobPostingsCollector.__new__(JobPostingsCollector)
    score, _tags = collector._analyze_job({
        "title": "Backend Developer",
        "full_text": "backend developer generative ai llm",
    })
    assert score >= 4


def test_news_analyzer_scores_high_keyword():
    collector = NewsCollector.__new__(NewsCollector)
    score, tags = collector._analyze_article(
        "ČNB uděluje pokutu", "regulátor dohled nad bankou"
    )
    assert score == 4
    assert "news" in tags
    assert "regulation" in tags


def test_news_analyzer_default_is_two():
    collector = NewsCollector.__new__(NewsCollector)
    score, _tags = collector._analyze_article("Nothing notable", "plain story")
    assert score == 2
