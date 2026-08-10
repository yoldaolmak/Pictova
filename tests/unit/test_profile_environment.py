from __future__ import annotations


def test_profile_loads_project_environment_before_returning(monkeypatch):
    from src.pictova.profiles import yoldaolmak

    loaded = []
    monkeypatch.setattr(yoldaolmak, "load_project_env", lambda: loaded.append(True))

    result = yoldaolmak.apply_environment()

    assert loaded == [True]
    assert result["profile"] == "yoldaolmak"
