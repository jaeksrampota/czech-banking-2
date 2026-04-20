import json

from src.models import Signal


def test_signal_auto_fills_id_detected_hash():
    sig = Signal(
        competitor_id="x", source="news", signal_type="news_article",
        title="Headline", content="Body",
    )
    assert sig.id and len(sig.id) == 36
    assert sig.detected_at
    assert len(sig.content_hash) == 64


def test_signal_hash_deterministic_from_key_fields():
    a = Signal(competitor_id="x", source="s", signal_type="t", title="same", content="same")
    b = Signal(competitor_id="x", source="s", signal_type="t", title="same", content="same")
    assert a.content_hash == b.content_hash


def test_signal_hash_differs_when_title_differs():
    a = Signal(competitor_id="x", source="s", signal_type="t", title="one", content="x")
    b = Signal(competitor_id="x", source="s", signal_type="t", title="two", content="x")
    assert a.content_hash != b.content_hash


def test_signal_to_dict_serializes_tags_and_metadata():
    sig = Signal(
        competitor_id="x", source="s", signal_type="t", title="t",
        tags=["a", "b"], metadata={"k": 1},
    )
    d = sig.to_dict()
    assert json.loads(d["tags"]) == ["a", "b"]
    assert json.loads(d["metadata"]) == {"k": 1}
    assert d["is_new"] == 1
