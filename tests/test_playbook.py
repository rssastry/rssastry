"""Tests for playbook.py - the living Rules of Engagement generator."""

import json
import os

import config
import playbook


def test_build_playbook_has_live_values():
    pb = playbook.build_playbook()
    markdown = playbook.render_markdown(pb)
    # live values must appear in the rendered text
    assert f"BUY_MIN_ENSEMBLE = {config.BUY_MIN_ENSEMBLE}" in markdown
    assert str(config.AI_BUY_MIN_CONFIDENCE) in markdown
    assert str(config.STYLE_MAX_HOLD_BARS["swing"]) in markdown
    # all six sections present
    for key in ("universe_and_styles", "entry_gate", "risk_limits", "exits",
                "lessons", "validation_journal"):
        assert key in pb["sections"]


def test_playbook_mentions_case_studies():
    markdown = playbook.render_markdown(playbook.build_playbook())
    assert "HINDCOPPER" in markdown
    assert "SUNPHARMA" in markdown


def test_write_playbook_writes_files(tmp_path):
    md = str(tmp_path / "playbook.md")
    js = str(tmp_path / "playbook.json")
    playbook.write_playbook(md, js)
    assert os.path.exists(md)
    assert os.path.exists(js)
    data = json.loads(open(js, encoding="utf-8").read())
    assert data["sections"]["entry_gate"]["title"].startswith("The BUY gate")
    assert "Auto-generated" in open(md, encoding="utf-8").read()