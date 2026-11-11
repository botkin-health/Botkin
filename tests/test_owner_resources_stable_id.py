"""Ресурсы владельца инсталляции — по стабильному ID, не по users.cohort (ADR-0014).

Пентест 08.11.2026: админка могла выставить любому пользователю cohort='owner',
и тот получал legacy-KB владельца (медкарту), генетику и Netatmo.
"""

import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import config.users as users_cfg

OWNER = 111
OTHER = 222


@pytest.fixture
def owner_id(monkeypatch):
    monkeypatch.setattr(users_cfg, "OWNER_USER_ID", OWNER)
    return OWNER


def test_parse_owner_id_prefers_env_then_admin(monkeypatch):
    monkeypatch.setenv("BOTKIN_OWNER_ID", "4242")
    assert users_cfg._parse_owner_id() == 4242
    monkeypatch.setenv("BOTKIN_OWNER_ID", "")
    monkeypatch.setattr(users_cfg, "ADMIN_USER_ID", 7)
    assert users_cfg._parse_owner_id() == 7


def test_cohort_owner_alone_grants_nothing(owner_id):
    assert users_cfg.is_installation_owner(SimpleNamespace(telegram_id=OWNER, cohort="external"))
    assert not users_cfg.is_installation_owner(SimpleNamespace(telegram_id=OTHER, cohort="owner"))
    assert not users_cfg.is_installation_owner(SimpleNamespace(telegram_id=None, cohort="owner"))


def test_no_owner_configured_means_nobody(monkeypatch):
    monkeypatch.setattr(users_cfg, "OWNER_USER_ID", 0)
    assert not users_cfg.is_installation_owner(SimpleNamespace(telegram_id=0, cohort="owner"))


def _legacy_kb(tmp_path):
    (tmp_path / "knowledge_base.json").write_text(json.dumps({"agent_corrections": {}}), encoding="utf-8")


def test_genetics_legacy_kb_only_for_owner_id(tmp_path, monkeypatch, owner_id):
    from core.health import genetics

    _legacy_kb(tmp_path)
    monkeypatch.setattr(genetics, "_PROJECT_ROOT", tmp_path)

    assert genetics.kb_path_for(SimpleNamespace(telegram_id=OTHER, cohort="owner")) is None
    assert genetics.kb_path_for(SimpleNamespace(telegram_id=OWNER, cohort="family")) == tmp_path / "knowledge_base.json"


def test_agent_kb_resolution_ignores_cohort(owner_id):
    from webhook.agent_tools import common

    path, source = common._resolve_user_kb_path(SimpleNamespace(telegram_id=OTHER, cohort="owner"))
    assert path is None and source == "kb-not-available"


def test_dashboard_air_block_only_for_owner_id(owner_id):
    import dashboard_blocks

    assert dashboard_blocks.is_installation_owner(SimpleNamespace(telegram_id=OWNER, cohort="external"))
    assert not dashboard_blocks.is_installation_owner(SimpleNamespace(telegram_id=OTHER, cohort="owner"))


def test_admin_cannot_assign_owner_cohort():
    from webhook import admin

    app = FastAPI()
    app.include_router(admin.router)
    app.dependency_overrides[admin.admin_auth] = lambda: "admin"
    r = TestClient(app).post(f"/admin/api/users/{OTHER}/cohort", json={"cohort": "owner"})
    assert r.status_code == 400
