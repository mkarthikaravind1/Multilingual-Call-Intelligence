import logging

from app.observability.logging import RedactUrlSecretsFilter


def _filtered(msg: str, *args) -> str:
    record = logging.LogRecord("uvicorn.error", logging.INFO, __file__, 1, msg, args, None)
    RedactUrlSecretsFilter().filter(record)
    return record.getMessage()


def test_the_stream_token_in_a_websocket_log_line_is_redacted():
    # As uvicorn logs it when the telephony stream connects.
    line = _filtered(
        '%s - "WebSocket %s" [accepted]',
        "127.0.0.1:56982",
        "/api/v1/calls/test-1/telephony-stream?token=eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJ0In0.sig",
    )

    assert "eyJ" not in line
    assert '/api/v1/calls/test-1/telephony-stream?token=REDACTED" [accepted]' in line


def test_tickets_and_other_parameters():
    line = _filtered("GET /live?call=c1&ticket=abc123&x=1 and ?access_token=zzz")

    assert line == "GET /live?call=c1&ticket=REDACTED&x=1 and ?access_token=REDACTED"


def test_other_messages_are_untouched():
    record = logging.LogRecord("app", logging.INFO, __file__, 1, "Call %r has %d turns", ("c1", 3), None)
    RedactUrlSecretsFilter().filter(record)

    assert (record.msg, record.args) == ("Call %r has %d turns", ("c1", 3))
