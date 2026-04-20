import difflib
import json
import logging
from dataclasses import dataclass, field

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# Fields that change frequently but carry no intelligence value
NOISE_FIELDS = {
    "datumAktualizace", "aktualizaceUdaju", "timestamp",
    "lastModified", "requestId", "version",
}


@dataclass
class Change:
    change_type: str  # "added", "removed", "modified"
    path: str         # JSON path or line reference
    old_value: str | None = None
    new_value: str | None = None


@dataclass
class ChangeResult:
    has_meaningful_changes: bool = False
    changes: list[Change] = field(default_factory=list)
    summary: str = ""

    def add(self, change: Change):
        self.changes.append(change)
        self.has_meaningful_changes = True

    def build_summary(self):
        if not self.changes:
            self.summary = "No changes detected."
            return
        parts = []
        for c in self.changes:
            if c.change_type == "added":
                parts.append(f"+ {c.path}: {c.new_value}")
            elif c.change_type == "removed":
                parts.append(f"- {c.path}: {c.old_value}")
            else:
                parts.append(f"~ {c.path}: {c.old_value!r} → {c.new_value!r}")
        self.summary = "\n".join(parts[:20])
        if len(parts) > 20:
            self.summary += f"\n... and {len(parts) - 20} more changes"


def detect_changes(
    old_content: str, new_content: str, content_type: str = "text"
) -> ChangeResult:
    if content_type == "json":
        result = _diff_json(old_content, new_content)
    elif content_type == "html":
        result = _diff_html(old_content, new_content)
    else:
        result = _diff_text(old_content, new_content)
    result.build_summary()
    return result


def _diff_json(old: str, new: str) -> ChangeResult:
    result = ChangeResult()
    try:
        old_data = json.loads(old)
        new_data = json.loads(new)
    except json.JSONDecodeError:
        return _diff_text(old, new)
    _compare_values(old_data, new_data, "", result)
    return result


def _compare_values(old, new, path: str, result: ChangeResult):
    if isinstance(old, dict) and isinstance(new, dict):
        all_keys = set(old.keys()) | set(new.keys())
        for key in sorted(all_keys):
            child_path = f"{path}.{key}" if path else key
            if key in NOISE_FIELDS:
                continue
            if key not in old:
                result.add(Change("added", child_path, None, _fmt(new[key])))
            elif key not in new:
                result.add(Change("removed", child_path, _fmt(old[key]), None))
            else:
                _compare_values(old[key], new[key], child_path, result)
    elif isinstance(old, list) and isinstance(new, list):
        # Compare lists by identity (content hash) rather than by position so
        # reordering doesn't explode into a wall of false-positive changes.
        old_by_key = _index_list(old)
        new_by_key = _index_list(new)
        for key in old_by_key.keys() - new_by_key.keys():
            result.add(Change("removed", f"{path}[{key}]", _fmt(old_by_key[key]), None))
        for key in new_by_key.keys() - old_by_key.keys():
            result.add(Change("added", f"{path}[{key}]", None, _fmt(new_by_key[key])))
        for key in old_by_key.keys() & new_by_key.keys():
            _compare_values(old_by_key[key], new_by_key[key], f"{path}[{key}]", result)
    else:
        if old != new:
            result.add(Change("modified", path, _fmt(old), _fmt(new)))


def _diff_text(old: str, new: str) -> ChangeResult:
    result = ChangeResult()
    old_lines = old.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)
    diff = list(difflib.unified_diff(old_lines, new_lines, n=0))

    for line in diff:
        line = line.rstrip("\n")
        if line.startswith("+++") or line.startswith("---") or line.startswith("@@"):
            continue
        if _is_noise_line(line):
            continue
        if line.startswith("+"):
            result.add(Change("added", "text", None, line[1:].strip()))
        elif line.startswith("-"):
            result.add(Change("removed", "text", line[1:].strip(), None))
    return result


def _diff_html(old: str, new: str) -> ChangeResult:
    old_text = _extract_text(old)
    new_text = _extract_text(new)
    return _diff_text(old_text, new_text)


def _extract_text(html: str) -> str:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
        tag.decompose()
    return soup.get_text(separator="\n", strip=True)


def _is_noise_line(line: str) -> bool:
    stripped = line.strip("+-").strip()
    if not stripped:
        return True
    return bool(stripped.isdigit())


def _fmt(value) -> str:
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False)[:200]
    return str(value)[:200]


# Dict fields that, when present, serve as a stable identity for a list item.
_IDENTITY_FIELDS = ("id", "uuid", "ico", "name", "nazev", "obchodniJmeno", "url")


def _index_list(items: list) -> dict:
    """Index list items by a stable identity so reordering doesn't look like a change.

    Uses a known identity field if the item is a dict and exposes one, else a
    hash of the item's JSON form. Falls back to position only when every item
    hashes to the same bucket (unlikely in real data).
    """
    result: dict = {}
    for idx, item in enumerate(items):
        key = None
        if isinstance(item, dict):
            for field_name in _IDENTITY_FIELDS:
                if field_name in item and item[field_name] not in (None, ""):
                    key = f"{field_name}={item[field_name]}"
                    break
        if key is None:
            try:
                key = f"hash={hash(json.dumps(item, ensure_ascii=False, sort_keys=True))}"
            except TypeError:
                key = f"pos={idx}"
        # Deduplicate collisions by suffixing the index.
        if key in result:
            key = f"{key}#{idx}"
        result[key] = item
    return result
