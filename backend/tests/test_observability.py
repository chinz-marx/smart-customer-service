import json
import logging

from app.observability.logger import ChatTrace, log_chat_trace, mask_message, mask_slots


def test_mask_message_hides_long_digit_runs() -> None:
    assert mask_message("我的手机号是 13800138000") == "我的手机号是 13****00"


def test_mask_slots_hides_sensitive_slot_values() -> None:
    masked = mask_slots({"order_id": "1234567890", "phone_tail": "1234", "activity_name": "618返现"})

    assert masked["order_id"] == "1234****7890"
    assert masked["phone_tail"] == "****"
    assert masked["activity_name"] == "618返现"


def test_log_chat_trace_writes_json(caplog) -> None:
    caplog.set_level(logging.INFO, logger="smart_customer_service.chat_trace")
    trace = ChatTrace(
        session_id="session-1",
        message_preview="奖励未到账",
        intent="reward_not_received",
        intent_confidence=0.95,
        slots={"order_id": "1234****7890"},
        decision_action="generate",
        decision_reason="ready_for_answer",
        provider="local-fallback",
        latency_ms=12.3,
        tool_name="reward_query",
        tool_success=True,
    )

    log_chat_trace(trace)

    payload = json.loads(caplog.records[-1].message)
    assert payload["session_id"] == "session-1"
    assert payload["intent"] == "reward_not_received"
    assert payload["tool_name"] == "reward_query"
