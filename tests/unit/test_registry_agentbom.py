"""SymBiote AgentBOM documents load as a native inventory source (shadowscan.agentbom)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from shadowscan.models import Finding, Kind, Surface
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
    assert entry.card["verification"] == "not-verified"


def test_only_subject_identities_are_approval_bindings() -> None:
    entry = Inventory.load([FIXTURE]).entries[0]
    assert entry.resources == ["k8s:prod-east/claims-prod/Deployment/claims-assistant"]
    assert entry.card["workload_uids"] == ["3f1c9a2e-uid-claims"]
    assert "https://mcp.claims.example.com/kb" in entry.card["component_resources"]
    assert "pkg:npm/%40acme/github-tools@1.4.2" in entry.card["component_resources"]


def _finding(resource: str, cluster: str = "prod-east") -> Finding:
    return Finding(
        surface=Surface.CLOUD,
        connector="cloud.kubernetes",
        kind=Kind.AGENT,
        title="Deployment",
        resource=resource,
        resource_type="kubernetes/Deployment",
        provider="kubernetes",
        account=cluster,
    )


def test_native_kubernetes_resource_matches_only_the_declared_workload() -> None:
    inventory = Inventory.load([FIXTURE])
    resource = "k8s:prod-east/claims-prod/Deployment/claims-assistant"
    assert inventory.match(_finding(resource)) is inventory.entries[0]
    for changed in (
        resource.replace("prod-east", "prod-west"),
        resource.replace("claims-prod", "claims-dev"),
        resource.replace("Deployment", "StatefulSet"),
        resource + "-other",
    ):
        assert inventory.match(_finding(changed)) is None


def test_dependencies_do_not_inherit_subject_approval() -> None:
    inventory = Inventory.load([FIXTURE])
    for resource in inventory.entries[0].card["component_resources"]:
        assert inventory.match(_finding(resource)) is None


@pytest.mark.parametrize(
    "identity", ["https://agent.example/*", "https://agent.example/a?b", "https://agent.example/[ab]"]
)
def test_imported_subject_resources_are_literal_not_glob_patterns(tmp_path, identity):
    doc = _doc()
    doc["agents"][0]["externalRefs"] = [{"type": "resource", "url": identity}]
    inventory = Inventory.load([_write(tmp_path, doc)])
    assert inventory.match(_finding(identity)) is inventory.entries[0]
    assert inventory.match(_finding("https://agent.example/ab")) is None
    assert inventory.match(_finding("https://agent.example/unapproved")) is None


def test_agentbom_shape_wins_over_plain_agents_list(tmp_path: Path) -> None:
    # An AgentBOM also has a top-level ``agents`` list; it must not be read as
    # a simple inventory (whose entries would be the BOM's entity mappings).
    inventory = Inventory.load([_write(tmp_path, _doc())])
    assert [e.agent_id for e in inventory.entries] == ["agent:claims-assistant"]


def test_subject_missing_from_agents_fails_closed(tmp_path: Path) -> None:
    doc = _doc()
    doc["subject"] = "agent:somebody-else"
    doc["snapshot"]["agentRef"] = doc["subject"]
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


@pytest.mark.parametrize(
    "digest", ["sha256:", "sha256:" + "a" * 63, "sha256:" + "g" * 64, "sha256:" + "A" * 64]
)
def test_sha256_prefix_is_not_a_digest(tmp_path, digest):
    doc = _doc()
    doc["snapshot"]["digest"] = digest
    with pytest.raises(InventoryValidationError, match="64 hex"):
        Inventory.load([_write(tmp_path, doc)])


@pytest.mark.parametrize("field,value", [("specVersion", "9.9"), ("subject", []), ("snapshot", None)])
def test_malformed_document_headers_fail_closed(tmp_path, field, value):
    doc = _doc()
    doc[field] = value
    with pytest.raises(InventoryValidationError):
        Inventory.load([_write(tmp_path, doc)])


@pytest.mark.parametrize(
    "field,value", [("agentRef", "agent:other"), ("serial", True), ("serial", 0), ("id", "snap:wrong")]
)
def test_snapshot_must_identify_its_subject_and_agree_with_serial_and_digest(tmp_path, field, value):
    doc = _doc()
    doc["snapshot"][field] = value
    with pytest.raises(InventoryValidationError):
        Inventory.load([_write(tmp_path, doc)])


def test_merkle_header_cannot_contradict_snapshot(tmp_path):
    doc = _doc()
    doc["merkle"]["root"] = "sha256:" + "0" * 64
    with pytest.raises(InventoryValidationError, match="merkle.root"):
        Inventory.load([_write(tmp_path, doc)])


@pytest.mark.parametrize("field", ["agents", "parties", "deployments", "toolServers"])
@pytest.mark.parametrize("value", [None, 123, {}, [None], [{"id": []}]])
def test_malformed_entity_collections_use_inventory_validation_errors(tmp_path, field, value):
    doc = _doc()
    doc[field] = value
    with pytest.raises(InventoryValidationError):
        Inventory.load([_write(tmp_path, doc)])


@pytest.mark.parametrize("field", ["agents", "parties", "deployments", "toolServers"])
def test_duplicate_entity_ids_fail_closed(tmp_path, field):
    doc = _doc()
    doc[field].append(doc[field][0].copy())
    with pytest.raises(InventoryValidationError, match="duplicate entity id"):
        Inventory.load([_write(tmp_path, doc)])


@pytest.mark.parametrize("field", ["agents", "parties", "deployments", "toolServers"])
def test_entity_ids_must_belong_to_their_collection(tmp_path, field):
    doc = _doc()
    doc[field][0]["id"] = "wrong:entity"
    if field == "agents":
        doc["subject"] = doc["snapshot"]["agentRef"] = "wrong:entity"
    with pytest.raises(InventoryValidationError, match="collection prefix"):
        Inventory.load([_write(tmp_path, doc)])


@pytest.mark.parametrize(
    "claim",
    [
        [],
        "conditionalAutomation",
        {"state": None, "value": "conditionalAutomation"},
        {"state": "present", "value": None},
        {"state": "unknown", "value": "conditionalAutomation", "unknownReason": "not-collected"},
        {"state": "unknown", "value": None},
        {"state": "absent-verified", "value": "conditionalAutomation"},
    ],
)
def test_malformed_claims_cannot_supply_an_autonomy_level(tmp_path, claim):
    doc = _doc()
    doc["agents"][0]["automationLevel"] = claim
    with pytest.raises(InventoryValidationError):
        Inventory.load([_write(tmp_path, doc)])


def test_omitted_claim_state_uses_the_producer_default(tmp_path):
    doc = _doc()
    del doc["agents"][0]["automationLevel"]["state"]
    assert Inventory.load([_write(tmp_path, doc)]).entries[0].autonomy_level == 3


def test_absent_verified_claim_does_not_mean_low_autonomy(tmp_path):
    doc = _doc()
    doc["agents"][0]["automationLevel"] = {"state": "absent-verified", "value": None}
    assert Inventory.load([_write(tmp_path, doc)]).entries[0].autonomy_level is None


def test_incomplete_workload_identity_has_no_guessed_approval(tmp_path):
    doc = _doc()
    del doc["deployments"][0]["environment"]["cluster"]
    assert not Inventory.load([_write(tmp_path, doc)]).entries[0].resources


def test_non_kubernetes_deployment_does_not_gain_a_kubernetes_binding(tmp_path):
    doc = _doc()
    doc["deployments"][0]["environment"]["kind"] = "vm"
    assert not Inventory.load([_write(tmp_path, doc)]).entries[0].resources


def test_conflicting_deployment_namespaces_are_rejected(tmp_path):
    doc = _doc()
    doc["deployments"][0]["environment"]["namespace"] = "another-tenant"
    with pytest.raises(InventoryValidationError, match="conflicts"):
        Inventory.load([_write(tmp_path, doc)])


def test_entity_budget_is_enforced_before_indexing(tmp_path, monkeypatch):
    monkeypatch.setattr("shadowscan.agentbom._MAX_ENTITIES", 0)
    with pytest.raises(InventoryValidationError, match="bounded list"):
        Inventory.load([_write(tmp_path, _doc())])


def test_mixes_with_other_inventory_formats(tmp_path: Path) -> None:
    simple = tmp_path / "agents.yaml"
    simple.write_text("agents:\n  - id: other-agent\n    owner: ops\n")
    inventory = Inventory.load([FIXTURE, simple])
    assert sorted(e.agent_id for e in inventory.entries) == ["agent:claims-assistant", "other-agent"]
