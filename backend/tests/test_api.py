import pytest
from fastapi.testclient import TestClient

from app import config
from app.models import Recording, init_db, session


@pytest.fixture
def client(tmp_path, monkeypatch):
    # Real API and database code, but a throwaway database and no LLM.
    from sqlmodel import SQLModel, create_engine

    from app import models

    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setattr(models, "engine", engine)
    init_db()
    monkeypatch.setattr(config.settings, "LLM_PROVIDER", "none")
    from app.main import app

    yield TestClient(app)
    SQLModel.metadata.drop_all(engine)


def _create(client, text="I love pizza"):
    res = client.post("/api/challenges", json={"text": text})
    assert res.status_code == 200
    return res.json()


def test_create_returns_a_private_results_code_separate_from_the_share_code(client):
    ch = _create(client)
    assert ch["slug"] and ch["results_token"] and ch["results_token"] != ch["slug"]
    assert len(ch["results_token"]) >= 16


def test_share_link_never_reveals_the_results_code_or_the_sentence(client):
    ch = _create(client)
    body = client.get(f"/api/challenges/{ch['slug']}").text
    assert ch["results_token"] not in body
    assert "pizza" not in body.lower()


def test_results_page_shows_the_sentence_and_attempts(client):
    ch = _create(client)
    res = client.get(f"/api/results/{ch['results_token']}").json()
    assert res["target_text"] == "I love pizza"
    assert res["slug"] == ch["slug"]
    assert res["recordings"] == []


def test_results_page_needs_the_secret_code(client):
    ch = _create(client)
    assert client.get(f"/api/results/{ch['slug']}").status_code == 404  # the share code is not enough
    assert client.get("/api/results/guess").status_code == 404


def test_recordings_are_only_reachable_by_their_secret_code(client):
    ch = _create(client)
    from app.models import Challenge
    from sqlmodel import select

    with session() as s:
        c = s.exec(select(Challenge).where(Challenge.slug == ch["slug"])).one()
        rec = Recording(challenge_id=c.id, input_path="x", status="done", output_path="/nonexistent.mp4")
        s.add(rec)
        s.commit()
        s.refresh(rec)
        number, code = rec.id, rec.public_id
    assert client.get(f"/api/recordings/{number}").status_code == 404  # sequential numbers don't work
    assert client.get(f"/api/recordings/{code}").json()["status"] == "done"
    listed = client.get(f"/api/results/{ch['results_token']}").json()["recordings"]
    assert [r["id"] for r in listed] == [code]
    assert listed[0]["video_url"] == f"/api/recordings/{code}/video"
