"""Dispatcher honesty (``cli_list.processCLI``) -- runs fully offline.

The dispatcher is the seam between ``girder_worker`` and each CLI script. Two
pins live here: an unknown CLI name fails LOUDLY (non-zero exit + stderr), and
the child's exit code is PROPAGATED so a crashed CLI marks the job failed rather
than silently succeeding with no outputs. ``--list_cli`` output is unchanged.
"""
import sys

import pytest

import cli_list  # repo root is on sys.path via tests/conftest.py


def test_unknown_cli_exits_nonzero_and_warns(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["cli_list.py", "NoSuchCLI"])
    with pytest.raises(SystemExit) as exc:
        cli_list.processCLI("cli_list.json")
    assert exc.value.code == 2
    assert "Unknown CLI" in capsys.readouterr().err


def test_list_cli_output_unchanged(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["cli_list.py", "--list_cli"])
    # Returns without sys.exit; must still print the full spec.
    cli_list.processCLI("cli_list.json")
    out = capsys.readouterr().out
    for task in (
        "OtsuSegmentation",
        "ThresholdSegmentation",
        "MedianFilter",
        "RegionOfInterestReport",
    ):
        assert task in out


def test_child_exit_code_is_propagated(monkeypatch):
    calls = {}

    def fake_call(argv, *a, **k):
        calls["argv"] = argv
        return 7

    monkeypatch.setattr(sys, "argv", ["cli_list.py", "OtsuSegmentation", "--help"])
    monkeypatch.setattr(cli_list.subprocess, "call", fake_call)
    with pytest.raises(SystemExit) as exc:
        cli_list.processCLI("cli_list.json")
    assert exc.value.code == 7
    # the child was invoked with the passthrough args
    assert calls["argv"][-1] == "--help"


def test_zero_exit_code_is_propagated(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["cli_list.py", "OtsuSegmentation", "--help"])
    monkeypatch.setattr(cli_list.subprocess, "call", lambda *a, **k: 0)
    with pytest.raises(SystemExit) as exc:
        cli_list.processCLI("cli_list.json")
    assert exc.value.code == 0
