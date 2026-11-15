"""Runs the Node-based renderer safety checks against widget.js and agent.js
(skipped when Node is not installed)."""
import os
import shutil
import subprocess

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
SCRIPT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "js", "renderer_safety.js")


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
@pytest.mark.parametrize("rel", ["frontend/widget.js", "frontend/agent/agent.js"])
def test_renderer_blocks_remote_media_and_spoofed_links(rel):
    r = subprocess.run(["node", SCRIPT, os.path.join(ROOT, rel)], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "FAIL" not in r.stdout


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
@pytest.mark.parametrize("rel", ["frontend/widget.js", "frontend/agent/agent.js"])
def test_escape_html_escapes_quotes(rel):
    """data-content="${escapeHtml(msg)}" must not be breakable by a quote in the message."""
    import re
    src = open(os.path.join(ROOT, rel), encoding="utf-8").read()
    m = re.search(r"function escapeHtml\(text\) \{.*?\n\}", src, re.S)
    assert m and '&quot;' in m.group(0) and '&#39;' in m.group(0)


def test_agent_js_has_suggestion_sanitizer_and_safe_urls():
    src = open(os.path.join(ROOT, "frontend/agent/agent.js"), encoding="utf-8").read()
    assert "sanitizeSuggestion(res.suggested_reply)" in src and "sanitizeSuggestion(data.suggested_reply)" in src
    assert "escapeAttr(safeHttpUrl(order.tracking_url))" in src
