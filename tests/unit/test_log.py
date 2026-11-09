import json

import pytest

from practicum.log import configure_logging, get_logger


def test_json_logging(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(json=True)
    get_logger().info("hello", answer=42)
    record = json.loads(capsys.readouterr().err.strip().splitlines()[-1])
    assert record["event"] == "hello"
    assert record["answer"] == 42
    assert record["level"] == "info"


def test_console_logging(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging()
    get_logger().info("hello", answer=42)
    line = capsys.readouterr().err
    assert "hello" in line
    assert "answer=42" in line
