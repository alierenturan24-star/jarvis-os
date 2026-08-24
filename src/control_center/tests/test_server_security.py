from pathlib import Path


def test_no_shell_or_trade_execution_endpoint_exists():
    source = Path("src/control_center/server.py").read_text(encoding="utf-8")
    assert "/api/shell" not in source and "/api/execute-trade" not in source
    assert "shell=True" not in source


def test_non_loopback_is_disabled_even_with_a_token():
    source = Path("src/control_center/server.py").read_text(encoding="utf-8")
    assert "Direct non-loopback binding is disabled" in source
    assert "0.0.0.0" not in source
