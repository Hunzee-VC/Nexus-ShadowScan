"""SymBiote AgentBOM documents load as a native inventory source (shadowscan.agentbom)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shadowscan.registry import Inventory, InventoryValidationError

FIXTURE = Path(__file__).parent.parent / "fixtures" / "symbiote" / "agentbom.claims-assistant.json"


def _doc() -> dict:
    return json.loads(FIXTURE.read_text())


def _write(tmp_path: Path, payload: dict) -> Path:
    path = tmp_path / "agentbom.json"
    path.write_text(json.dumps(payload))
    return path


def test_fixture_loads_as_one_sanctioned_entry() -> None:
    inventory = Inventory.load([FIXTURE])
    assert len(inventory.entries) == 1  # the subject agent, never the entity list
    entry = inventory.entries[0]
    assert entry.agent_id == "agent:claims-assistant"
    assert entry.name == "Claims Assistant"
    assert entry.owner == "Claims IT"
    assert entry.autonomy_level == 3  # conditionalAutomation -> L3
    assert entry.tags == ["agentbom"]
    assert "claims-assistant" in entry.names
    assert entry.frameworks == ["framework.langgraph"]
    assert entry.card["schema"] == "symbiote-agentbom"
    assert entry.card["snapshot_digest"].startswith("sha256:")
    assert entry.card["snapshot_serial"] == 1


def test_discovery_resources_come_from_deployment_servers_and_purls() -> None:
    entry = Inventory.load([FIXTURE]).entries[0]
    assert "3f1c9a2e-uid-claims" in entry.resources  # workload uid
    assert "k8s:claims-prod/claims-assistant" in entry.resources
    assert "https://mcp.claims.example.com/kb" in entry.resources  # remote server endpoint
    assert "pkg:npm/%40acme/github-tools@1.4.2" in entry.resources  # pinned package


def test_agentbom_shape_wins_over_plain_agents_list(tmp_path: Path) -> None:
    # An AgentBOM also has a top-level ``agents`` list; it must not be read as
    # a simple inventory (whose entries would be the BOM's entity mappings).
    inventory = Inventory.load([_write(tmp_path, _doc())])
    assert [e.agent_id for e in inventory.entries] == ["agent:claims-assistant"]


def test_subject_missing_from_agents_fails_closed(tmp_path: Path) -> None:
    doc = _doc()
    doc["subject"] = "agent:somebody-else"
    with pytest.raises(InventoryValidationError, match="not among the agents"):
        Inventory.load([_write(tmp_path, doc)])


def test_unknown_automation_ladder_value_fails_closed(tmp_path: Path) -> None:
    doc = _doc()
    doc["agents"][0]["automationLevel"]["value"] = "warpSpeed"
    with pytest.raises(InventoryValidationError, match="isoAutomationLevel"):
        Inventory.load([_write(tmp_path, doc)])


def test_unknown_claim_state_contributes_no_level(tmp_path: Path) -> None:
    doc = _doc()
    doc["agents"][0]["automationLevel"] = {
        "value": None,
        "state": "unknown",
        "assurance": "declared",
        "unknownReason": "not-collected",
    }
    entry = Inventory.load([_write(tmp_path, doc)]).entries[0]
    assert entry.autonomy_level is None  # unknown never counts as a low level


def test_malformed_snapshot_digest_fails_closed(tmp_path: Path) -> None:
    doc = _doc()
    doc["snapshot"]["digest"] = "md5:nope"
    with pytest.raises(InventoryValidationError, match="sha256"):
        Inventory.load([_write(tmp_path, doc)])


def test_mixes_with_other_inventory_formats(tmp_path: Path) -> None:
    simple = tmp_path / "agents.yaml"
    simple.write_text("agents:\n  - id: other-agent\n    owner: ops\n")
    inventory = Inventory.load([FIXTURE, simple])
    assert sorted(e.agent_id for e in inventory.entries) == ["agent:claims-assistant", "other-agent"]
