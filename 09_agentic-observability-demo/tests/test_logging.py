import json
import logging

from app.logging_setup import JsonFormatter, mask_secrets, request_id_var, setup_logging

logger = logging.getLogger("app.test")


def test_each_line_is_valid_json_with_standard_fields(json_logs):
    logger.info("hello", extra={"operation": "test.op", "status": "success", "duration_ms": 12.5})
    line = json_logs()[0]

    assert line["level"] == "INFO"
    assert line["message"] == "hello"
    assert line["logger"] == "app.test"
    assert line["operation"] == "test.op"
    assert line["duration_ms"] == 12.5
    assert "timestamp" in line


def test_request_id_is_added_to_logs(json_logs):
    token = request_id_var.set("req-42")
    try:
        logger.info("inside request")
    finally:
        request_id_var.reset(token)
    logger.info("outside request")

    lines = json_logs()
    assert lines[0]["request_id"] == "req-42"
    assert lines[1]["request_id"] == "-"


def test_exception_details_are_included(json_logs):
    try:
        raise ValueError("bad value")
    except ValueError:
        logger.error("failed", exc_info=True)

    exception = json_logs()[0]["exception"]
    assert exception["type"] == "ValueError"
    assert exception["message"] == "bad value"
    assert "Traceback" in exception["traceback"]


def test_secrets_are_masked_in_messages_and_fields(json_logs):
    logger.warning("key is sk-abcdefghijklmnop1234", extra={"api_key": "anything", "note": "lsv2_pt_abcdef123456"})
    line = json_logs()[0]

    raw = json.dumps(line)
    assert "sk-abcdefghijklmnop1234" not in raw
    assert "lsv2_pt_abcdef123456" not in raw
    assert line["api_key"] == "[REDACTED]"


def test_mask_secrets_leaves_normal_text_alone():
    assert mask_secrets("task-123 finished") == "task-123 finished"


def test_setup_logging_writes_json_to_file(tmp_path):
    log_file = tmp_path / "logs" / "app.log"
    app_logger = setup_logging("INFO", log_file)
    try:
        logging.getLogger("app.agent").info("written to file", extra={"status": "success"})
        for handler in app_logger.handlers:
            handler.flush()
        line = json.loads(log_file.read_text(encoding="utf-8").strip().splitlines()[-1])
        assert line["message"] == "written to file"
        assert line["status"] == "success"
    finally:
        for handler in list(app_logger.handlers):
            app_logger.removeHandler(handler)
            handler.close()


def test_debug_lines_are_dropped_at_info_level(tmp_path):
    app_logger = setup_logging("INFO", tmp_path / "app.log")
    try:
        logging.getLogger("app.agent").debug("too noisy")
        assert (tmp_path / "app.log").read_text(encoding="utf-8") == ""
    finally:
        for handler in list(app_logger.handlers):
            app_logger.removeHandler(handler)
            handler.close()


def test_formatter_can_be_used_on_its_own():
    record = logging.LogRecord("app.x", logging.INFO, __file__, 1, "msg %s", ("one",), None)
    assert json.loads(JsonFormatter().format(record))["message"] == "msg one"
