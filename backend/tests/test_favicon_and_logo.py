import os
import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_favicon_ico_endpoint(client):
    res = client.get("/favicon.ico")
    assert res.status_code == 200
    assert "image" in res.headers.get("content-type", "")
    assert len(res.content) > 500


def test_agent_favicon_ico_endpoint(client):
    res = client.get("/agent/favicon.ico")
    assert res.status_code == 200
    assert "image" in res.headers.get("content-type", "")


def test_favicon_svg_endpoint(client):
    res = client.get("/favicon.svg")
    assert res.status_code == 200
    assert "svg" in res.headers.get("content-type", "")
    assert b"<svg" in res.content


def test_wren_mark_svg_endpoints(client):
    for path in ["/images/wren-mark.svg", "/agent/images/wren-mark.svg"]:
        res = client.get(path)
        assert res.status_code == 200, f"Failed for {path}"
        assert "svg" in res.headers.get("content-type", "")
        assert b"<svg" in res.content


def test_favicon_files_exist_on_disk():
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    repo_root = os.path.dirname(backend_dir)
    
    expected_files = [
        os.path.join(repo_root, "frontend", "favicon.ico"),
        os.path.join(repo_root, "frontend", "favicon.svg"),
        os.path.join(repo_root, "frontend", "apple-touch-icon.png"),
        os.path.join(repo_root, "frontend", "images", "wren-mark.svg"),
        os.path.join(repo_root, "frontend", "agent", "images", "wren-mark.svg"),
        os.path.join(repo_root, "frontend", "agent", "favicon.ico"),
        os.path.join(repo_root, "backend", "app", "static", "favicon.ico"),
        os.path.join(repo_root, "backend", "app", "static", "images", "wren-mark.svg"),
        os.path.join(repo_root, "backend", "app", "static", "agent", "images", "wren-mark.svg"),
    ]
    
    for f in expected_files:
        assert os.path.exists(f), f"Missing file: {f}"
        assert os.path.getsize(f) > 0, f"Empty file: {f}"
