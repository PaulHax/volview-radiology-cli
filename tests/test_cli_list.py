"""Tests for ``cli_list.processCLI`` dispatch and error handling.

The dispatcher is the seam between ``girder_worker`` and each CLI script. Two
important behaviors are that unknown CLI names fail with an error and child exit
codes propagate to the caller.
"""
import json
import sys

import pytest

import cli_list  # repo root is on sys.path via tests/conftest.py


def test_unknown_cli_exits_nonzero_and_warns(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["cli_list.py", "NoSuchCLI"])
    with pytest.raises(SystemExit) as exc:
        cli_list.processCLI("cli_list.json")
    assert exc.value.code == 2
    assert "Unknown CLI" in capsys.readouterr().err


@pytest.mark.parametrize("manifest, expected", [
    ("cli_list.json", {"GenerateSegmentRulers", "ExportSegmentStatistics"}),
    ("examples/cli_list.json", {
        "MaskedMedianFilter", "MedianFilter", "OtsuSegmentation", "ThresholdSegmentation",
    }),
])
def test_list_cli_output_contains_only_registered_tasks(monkeypatch, capsys, manifest, expected):
    monkeypatch.setattr(sys, "argv", ["cli_list.py", "--list_cli"])
    # Returns without sys.exit; must still print the full spec.
    cli_list.processCLI(manifest)
    tasks = json.loads(capsys.readouterr().out)
    assert set(tasks) == expected
    assert {"RegionOfInterestRulers", "RegionOfInterestReport"}.isdisjoint(tasks)


@pytest.mark.parametrize("manifest, task", [
    ("cli_list.json", "MaskedMedianFilter"),
    ("cli_list.json", "MedianFilter"),
    ("cli_list.json", "OtsuSegmentation"),
    ("cli_list.json", "ThresholdSegmentation"),
    ("examples/cli_list.json", "GenerateSegmentRulers"),
    ("examples/cli_list.json", "ExportSegmentStatistics"),
])
def test_task_from_other_image_is_rejected(monkeypatch, manifest, task):
    monkeypatch.setattr(sys, "argv", ["cli_list.py", task, "--xml"])
    with pytest.raises(SystemExit) as exc:
        cli_list.processCLI(manifest)
    assert exc.value.code == 2


def test_child_exit_code_is_propagated(monkeypatch):
    calls = {}

    def fake_call(argv, *a, **k):
        calls["argv"] = argv
        return 7

    monkeypatch.setattr(sys, "argv", ["cli_list.py", "GenerateSegmentRulers", "--help"])
    monkeypatch.setattr(cli_list.subprocess, "call", fake_call)
    with pytest.raises(SystemExit) as exc:
        cli_list.processCLI("cli_list.json")
    assert exc.value.code == 7
    # the child was invoked with the passthrough args
    assert calls["argv"][-1] == "--help"


def test_zero_exit_code_is_propagated(monkeypatch):
    monkeypatch.setattr(sys, "argv", ["cli_list.py", "GenerateSegmentRulers", "--help"])
    monkeypatch.setattr(cli_list.subprocess, "call", lambda *a, **k: 0)
    with pytest.raises(SystemExit) as exc:
        cli_list.processCLI("cli_list.json")
    assert exc.value.code == 0
