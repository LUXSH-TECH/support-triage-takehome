import pytest

from app.classifier import classify


@pytest.mark.parametrize("msg,expected", [
    ("I'd like to send it back", "returns"),
    ("It arrived cracked", "damaged_item"),
    ("It arrived broken and I want a refund", "damaged_item"),   # damaged-item policy wins over returns
    ("Where is my parcel? It is late", "shipping"),
    ("Late and broken", "other"),                                  # mixed -> human review
    ("Extend my warranty", "other"),
    ("hello", "other"),
])
def test_classify(msg, expected):
    assert classify(msg) == expected