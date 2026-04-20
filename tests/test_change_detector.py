import json

from src.analysis.change_detector import detect_changes


def test_text_diff_detects_added_and_removed_lines():
    result = detect_changes("hello\nworld\n", "hello\nbrave\nworld\n", "text")
    assert result.has_meaningful_changes
    kinds = {c.change_type for c in result.changes}
    assert "added" in kinds


def test_json_diff_ignores_noise_fields():
    old = json.dumps({"name": "ACME", "datumAktualizace": "2020-01-01"})
    new = json.dumps({"name": "ACME", "datumAktualizace": "2025-01-01"})
    result = detect_changes(old, new, "json")
    assert not result.has_meaningful_changes


def test_json_diff_detects_field_modification():
    old = json.dumps({"name": "ACME"})
    new = json.dumps({"name": "ACME Bank"})
    result = detect_changes(old, new, "json")
    assert result.has_meaningful_changes
    assert any(c.change_type == "modified" and c.path == "name" for c in result.changes)


def test_json_list_reorder_is_not_a_change():
    old = json.dumps([{"name": "Alice"}, {"name": "Bob"}])
    new = json.dumps([{"name": "Bob"}, {"name": "Alice"}])
    result = detect_changes(old, new, "json")
    assert not result.has_meaningful_changes, [
        (c.change_type, c.path, c.old_value, c.new_value) for c in result.changes
    ]


def test_json_list_new_member_is_added():
    old = json.dumps([{"name": "Alice"}])
    new = json.dumps([{"name": "Alice"}, {"name": "Bob"}])
    result = detect_changes(old, new, "json")
    assert result.has_meaningful_changes
    added = [c for c in result.changes if c.change_type == "added"]
    assert len(added) == 1
    assert "Bob" in (added[0].new_value or "")


def test_identical_json_has_no_changes():
    same = json.dumps({"name": "ACME", "members": ["a", "b"]})
    result = detect_changes(same, same, "json")
    assert not result.has_meaningful_changes


def test_summary_truncates_to_20_lines():
    old = json.dumps({f"k{i}": i for i in range(30)})
    new = json.dumps({f"k{i}": i + 1 for i in range(30)})
    result = detect_changes(old, new, "json")
    assert "more changes" in result.summary
