import json
import logging
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from src.analysis.change_detector import detect_changes
from src.collectors.base import BaseCollector, CollectorError
from src.models import Signal

logger = logging.getLogger(__name__)

ARES_API_URL = "https://ares.gov.cz/ekonomicke-subjekty-v-be/rest/ekonomicke-subjekty/{ico}"
JUSTICE_BASE = "https://or.justice.cz/ias/ui/"
JUSTICE_SEARCH_URL = "https://or.justice.cz/ias/ui/rejstrik-$firma"
JUSTICE_VYSLEDKY_URL = "https://or.justice.cz/ias/ui/rejstrik-firma.vysledky"


class AresCollector(BaseCollector):
    name = "ares"
    rate_limit_delay = 3.0
    required_source_key = "ares_ico"

    def collect(self, competitor_id: str) -> list[Signal]:
        config = self._load_competitor_config(competitor_id)
        ico = config["sources"]["ares_ico"]
        signals = []

        signals.extend(self._collect_ares_api(competitor_id, ico))
        signals.extend(self._collect_justice(competitor_id, ico))

        return signals

    # ── ARES REST API ────────────────────────────────────────────

    def _collect_ares_api(self, competitor_id: str, ico: str) -> list[Signal]:
        url = ARES_API_URL.format(ico=ico)
        snapshot_key = f"ares_api:{ico}"

        try:
            content, has_changed = self._fetch_and_store_snapshot(
                competitor_id, snapshot_key, url,
                headers={"Accept": "application/json"},
            )
        except CollectorError:
            logger.warning("ARES API unreachable for ICO %s", ico)
            return []

        if not has_changed:
            logger.info("No ARES changes for %s", competitor_id)
            return []

        data = json.loads(content)
        prev = self.db.get_previous_snapshot(competitor_id, self.name, snapshot_key)

        if prev is None:
            return [Signal(
                competitor_id=competitor_id,
                source=self.name,
                signal_type="baseline",
                title=f"ARES baseline captured for {data.get('obchodniJmeno', ico)}",
                content=f"Company: {data.get('obchodniJmeno')}, ICO: {ico}",
                url=url,
                severity=1,
                tags=["baseline", "ares"],
                metadata={"ico": ico, "name": data.get("obchodniJmeno")},
            )]

        changes = detect_changes(prev["content"], content, "json")

        if not changes.has_meaningful_changes:
            return []

        signals = []
        for change in changes.changes:
            signal_type, severity = self._classify_ares_change(change.path)
            signals.append(Signal(
                competitor_id=competitor_id,
                source=self.name,
                signal_type=signal_type,
                title=f"ARES change: {change.path}",
                content=changes.summary,
                url=url,
                severity=severity,
                tags=["ares", signal_type],
                metadata={"field": change.path, "old": change.old_value, "new": change.new_value},
                change_summary=f"{change.path}: {change.old_value} → {change.new_value}",
            ))
        return signals

    def _classify_ares_change(self, path: str) -> tuple[str, int]:
        path_lower = path.lower()
        if "sidlo" in path_lower:
            return "address_change", 2
        if "statutarni" in path_lower or "organ" in path_lower:
            return "board_change", 4
        if "kapital" in path_lower or "zakladni" in path_lower:
            return "capital_change", 4
        if "nace" in path_lower or "cinnost" in path_lower:
            return "nace_change", 3
        if "registrac" in path_lower or "rejstrik" in path_lower:
            return "registration_change", 3
        if "obchodniJmeno" in path_lower or "nazev" in path_lower:
            return "name_change", 5
        return "ares_change", 2

    # ── Justice.cz ───────────────────────────────────────────────

    def _collect_justice(self, competitor_id: str, ico: str) -> list[Signal]:
        snapshot_key = f"justice:{ico}"

        try:
            resp = self._fetch(
                JUSTICE_SEARCH_URL,
                params={"ico": ico, "jenPlatworke": "PLATNE"},
            )
        except CollectorError:
            logger.warning("Justice.cz unreachable for ICO %s", ico)
            return []

        excerpt_link = self._find_excerpt_link(resp.text)

        if not excerpt_link:
            # Try the vysledky page
            try:
                resp = self._fetch(
                    JUSTICE_VYSLEDKY_URL,
                    params={"ico": ico, "jenPlatne": "PLATNE", "typHledani": "STARTS_WITH"},
                )
                excerpt_link = self._find_excerpt_link(resp.text)
            except CollectorError:
                pass

        if not excerpt_link:
            logger.warning("No Justice.cz excerpt found for ICO %s", ico)
            return []

        excerpt_link = urljoin(JUSTICE_BASE, excerpt_link)

        try:
            content, has_changed = self._fetch_and_store_snapshot(
                competitor_id, snapshot_key, excerpt_link,
            )
        except CollectorError:
            return []

        if not has_changed:
            return []

        board = self._parse_justice_excerpt(content)
        prev = self.db.get_previous_snapshot(competitor_id, self.name, snapshot_key)

        if prev is None:
            members = board.get("board_members", [])
            return [Signal(
                competitor_id=competitor_id,
                source=self.name,
                signal_type="baseline",
                title=f"Justice.cz baseline: {len(members)} board members",
                content="\n".join(m.get("name", "?") for m in members),
                url=excerpt_link,
                severity=1,
                tags=["baseline", "justice"],
                metadata=board,
            )]

        old_board = self._parse_justice_excerpt(prev["content"])
        return self._diff_boards(competitor_id, excerpt_link, old_board, board)

    def _find_excerpt_link(self, html: str) -> str | None:
        soup = BeautifulSoup(html, "lxml")
        for a in soup.select("a[href]"):
            href = a.get("href", "")
            if "vypis-sl-firma" in href or "vypis-vypis" in href:
                return href
        return None

    def _parse_justice_excerpt(self, html: str) -> dict:
        soup = BeautifulSoup(html, "lxml")
        result = {"board_members": [], "supervisory_board": [], "capital": "", "activities": []}

        current_section = None
        for el in soup.select(".vr-hlavicka, .vr-obsah, div.aunp-content h2, div.aunp-content div"):
            text = el.get_text(strip=True)
            text_lower = text.lower()

            if "statutární orgán" in text_lower or "jednatel" in text_lower:
                current_section = "board_members"
            elif "dozorčí rad" in text_lower:
                current_section = "supervisory_board"
            elif "základní kapitál" in text_lower:
                current_section = "capital"
            elif "předmět" in text_lower and "podnikání" in text_lower:
                current_section = "activities"
            elif current_section in ("board_members", "supervisory_board"):
                name_parts = text.split(",")
                if len(name_parts) >= 1 and len(name_parts[0]) > 3:
                    entry = {"name": name_parts[0].strip(), "raw": text}
                    if len(name_parts) > 1:
                        entry["details"] = ",".join(name_parts[1:]).strip()
                    result[current_section].append(entry)
            elif current_section == "capital":
                if text and not result["capital"]:
                    result["capital"] = text
                    current_section = None
            elif current_section == "activities" and text:
                result["activities"].append(text)

        return result

    def _diff_boards(
        self, competitor_id: str, url: str, old: dict, new: dict
    ) -> list[Signal]:
        signals = []

        # Board and supervisory board diffs
        board_configs = [
            ("board_members", "board", 5, 4),
            ("supervisory_board", "supervisory board", 4, 3),
        ]
        for board_key, label, sev_add, sev_remove in board_configs:
            old_names = {m["name"] for m in old.get(board_key, [])}
            new_names = {m["name"] for m in new.get(board_key, [])}

            for name in new_names - old_names:
                signals.append(Signal(
                    competitor_id=competitor_id,
                    source=self.name,
                    signal_type="board_change",
                    title=f"New {label} member: {name}",
                    content=f"{name} added to {label}",
                    url=url,
                    severity=sev_add,
                    tags=[board_key, "new_member"],
                    metadata={"name": name, "change": "added", "board": board_key},
                ))

            for name in old_names - new_names:
                signals.append(Signal(
                    competitor_id=competitor_id,
                    source=self.name,
                    signal_type="board_change",
                    title=f"{label.capitalize()} member removed: {name}",
                    content=f"{name} removed from {label}",
                    url=url,
                    severity=sev_remove,
                    tags=[board_key, "removed_member"],
                    metadata={"name": name, "change": "removed", "board": board_key},
                ))

        # Capital changes
        if old.get("capital") and new.get("capital") and old["capital"] != new["capital"]:
            signals.append(Signal(
                competitor_id=competitor_id,
                source=self.name,
                signal_type="capital_change",
                title=f"Capital change: {old['capital']} → {new['capital']}",
                content=f"Share capital changed from {old['capital']} to {new['capital']}",
                url=url,
                severity=4,
                tags=["capital"],
                metadata={"old": old["capital"], "new": new["capital"]},
            ))

        return signals
