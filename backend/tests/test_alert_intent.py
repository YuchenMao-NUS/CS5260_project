from smartflight.agent import extract_preference
from smartflight.services import nlu


def test_agent_alert_inference_enables_notify_without_me():
    result = extract_preference._infer_alert_request(
        "notify e0895914@u.nus.edu when available",
        None,
    )
    assert result is not None
    assert result["enabled"] is True
    assert result["intent"] == "create"
    assert result["email"] == "e0895914@u.nus.edu"


def test_nlu_alert_inference_enables_notify_without_me():
    result = nlu._infer_alert_request(
        "notify e0895914@u.nus.edu when available",
        None,
    )
    assert result is not None
    assert result["enabled"] is True
    assert result["intent"] == "create"
    assert result["email"] == "e0895914@u.nus.edu"


def test_nlu_alert_inference_detects_cancel_intent():
    result = nlu._infer_alert_request(
        "don't notify e0895914@u.nus.edu anymore",
        {"enabled": True, "email": "e0895914@u.nus.edu", "intent": "create"},
    )
    assert result is not None
    assert result["enabled"] is False
    assert result["intent"] == "cancel"

