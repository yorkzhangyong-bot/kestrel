"""The fake send_email tool records calls and sends nothing (FR-035)."""
from tools.send_email import EmailRecorder


def test_a_call_is_recorded_with_its_arguments():
    recorder = EmailRecorder()
    recorder.send_email(to="amy@example.com", subject="Classification", body="HS 7310")
    assert len(recorder.calls) == 1
    call = recorder.calls[0]
    assert call.to == "amy@example.com" and call.subject == "Classification" and call.body == "HS 7310"


def test_it_returns_a_plausible_success():
    assert "amy@example.com" in EmailRecorder().send_email(to="amy@example.com")


def test_calls_accumulate_in_order():
    recorder = EmailRecorder()
    recorder.send_email(to="first@example.com")
    recorder.send_email(to="second@example.com")
    assert [c.to for c in recorder.calls] == ["first@example.com", "second@example.com"]


def test_the_recorder_can_be_cleared():
    recorder = EmailRecorder()
    recorder.send_email(to="amy@example.com")
    recorder.clear()
    assert recorder.calls == []


def test_calls_are_readable_as_dicts_for_the_debug_endpoint():
    recorder = EmailRecorder()
    recorder.send_email(to="amy@example.com", subject="s", body="b")
    assert recorder.calls[0].as_dict() == {"to": "amy@example.com", "subject": "s", "body": "b"}
