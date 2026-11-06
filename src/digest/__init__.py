"""Competitor digest: a readable weekly/monthly summary of the scraped FINeCIM tables.

``build_digest`` turns the database into a plain dict (the same content the API returns
as JSON); ``render_markdown`` / ``render_html`` turn that dict into text and
``write_digest`` saves the files. See finecim-research/DIGEST.md.
"""

from src.digest.build import (
    MARKET_SEGMENT_SLUG,
    PERIODS,
    Period,
    build_digest,
    compute_period,
    diff_atributy,
    format_date_cz,
    rank_by_tier,
)
from src.digest.render import digest_filename, render_html, render_markdown, write_digest

__all__ = [
    "MARKET_SEGMENT_SLUG",
    "PERIODS",
    "Period",
    "build_digest",
    "compute_period",
    "diff_atributy",
    "digest_filename",
    "format_date_cz",
    "rank_by_tier",
    "render_html",
    "render_markdown",
    "write_digest",
]
