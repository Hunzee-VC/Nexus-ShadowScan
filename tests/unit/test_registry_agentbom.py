"""SymBiote AgentBOM documents load as a native inventory source (shadowscan.agentbom)."""

from __future__ import annotations

import functools
import json
import re
from pathlib import Path

import pytest

from shadowscan.agentbom import ISO_TO_LEVEL
from shadowscan.autonomy import LEVELS
from shadowscan.models import Finding, Kind, Surface
from shadowscan.registry import Inventory, InventoryValidationError, literal_resource_pattern
from shadowscan.utils import files

FIXTURE = Path(__file__).parent.parent / "fixtures" / "symbiote" / "agentbom.claims-assistant.json"
SYMBIOTE_DOC = Path(__file__).resolve().parents[2] / "docs" / "integrations" / "symbiote.md"
K8S_IDENTITY = "k8s:prod-east/claims-prod/Deployment/claims-assistant"


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


# --- Identity, reference and id validation -------------------------------------


def _subject_id(doc: dict, identity: str) -> None:
    doc["subject"] = doc["snapshot"]["agentRef"] = doc["agents"][0]["id"] = identity


def _set_identity_part(doc: dict, part: str, value: str) -> None:
    deployment = doc["deployments"][0]
    if part == "cluster":
        deployment["environment"]["cluster"] = value
    elif part == "namespace":
        # The environment and workload namespaces must agree before the part itself is checked.
        deployment["environment"]["namespace"] = deployment["workloadRef"]["namespace"] = value
    else:
        deployment["workloadRef"][part] = value


def _workload_identity(doc: dict) -> str:
    deployment = doc["deployments"][0]
    workload = deployment["workloadRef"]
    parts = (deployment["environment"]["cluster"], workload["namespace"], workload["kind"], workload["name"])
    return "k8s:" + "/".join(parts)


@pytest.mark.parametrize("part", ["cluster", "namespace", "kind", "name"])
def test_slash_in_any_kubernetes_identity_component_is_rejected(tmp_path, part):
    # The identity is joined with slashes, so a component carrying one could spell
    # another workload's ``k8s:<cluster>/<namespace>/<kind>/<name>``.
    doc = _doc()
    _set_identity_part(doc, part, "claims-prod/claims-assistant")
    with pytest.raises(InventoryValidationError, match="cannot contain slashes"):
        Inventory.load([_write(tmp_path, doc)])


@pytest.mark.parametrize("reference", ["party:nobody", "server:github", "agent:claims-assistant"])
def test_owner_reference_must_name_a_party_in_the_document(tmp_path, reference):
    doc = _doc()
    doc["agents"][0]["ownerRef"] = reference
    with pytest.raises(InventoryValidationError, match="does not identify a party"):
        Inventory.load([_write(tmp_path, doc)])


def test_owner_reference_must_be_a_string(tmp_path):
    doc = _doc()
    doc["agents"][0]["ownerRef"] = ["party:claims-it"]
    with pytest.raises(InventoryValidationError, match="ownerRef"):
        Inventory.load([_write(tmp_path, doc)])


def test_subject_without_owner_reference_has_no_owner(tmp_path):
    doc = _doc()
    doc["agents"][0]["ownerRef"] = None
    assert Inventory.load([_write(tmp_path, doc)]).entries[0].owner is None


def _bad_ids(prefix: str) -> dict[str, str]:
    """Entity ids the ``[a-z][a-z0-9-]*:[A-Za-z0-9._~/@+-]+`` form or the 512-character limit refuses."""
    return {
        "whitespace": f"{prefix}:claims assistant",
        "glob-star": f"{prefix}:claims*",
        "glob-bracket": f"{prefix}:claims[0]",
        "non-ascii": f"{prefix}:claimsé",
        "uppercase-collection": f"{prefix.capitalize()}:claims-assistant",
        "empty-local-part": f"{prefix}:",
        "no-separator": f"{prefix}-claims-assistant",
        "513-characters": f"{prefix}:" + "a" * (513 - len(prefix) - 1),
    }


@pytest.mark.parametrize("flaw", list(_bad_ids("agent")))
@pytest.mark.parametrize("collection", ["subject", "parties"])
def test_malformed_entity_ids_are_rejected_without_being_echoed(tmp_path, collection, flaw):
    doc = _doc()
    if collection == "subject":
        identity = _bad_ids("agent")[flaw]
        _subject_id(doc, identity)
    else:
        identity = _bad_ids("party")[flaw]
        doc["parties"][0]["id"] = doc["agents"][0]["ownerRef"] = identity
    with pytest.raises(InventoryValidationError, match="expected an AgentBOM entity id") as caught:
        Inventory.load([_write(tmp_path, doc)])
    assert identity not in str(caught.value)


def test_entity_id_limit_admits_exactly_512_characters(tmp_path):
    doc = _doc()
    _subject_id(doc, "agent:" + "a" * (512 - len("agent:")))
    assert len(Inventory.load([_write(tmp_path, doc)]).entries[0].agent_id) == 512


# --- Literal binding of glob metacharacters -------------------------------------

_GLOB_EXPANSIONS = {"x*y": "xzzy", "x?y": "xzy", "x[ab]y": "xay"}


@pytest.mark.parametrize("part", ["cluster", "namespace", "kind", "name"])
@pytest.mark.parametrize("value", sorted(_GLOB_EXPANSIONS))
def test_glob_characters_inside_kubernetes_identity_parts_bind_literally(tmp_path, part, value):
    doc = _doc()
    _set_identity_part(doc, part, value)
    inventory = Inventory.load([_write(tmp_path, doc)])
    identity = _workload_identity(doc)
    assert inventory.entries[0].resources == [literal_resource_pattern(identity)]
    assert inventory.match(_finding(identity)) is inventory.entries[0]
    assert inventory.match(_finding(identity.replace(value, _GLOB_EXPANSIONS[value]))) is None


@pytest.mark.parametrize(
    "identity", ["https://agent.example/*", "https://agent.example/a?b", "https://agent.example/[ab]"]
)
def test_a2a_card_url_is_a_literal_binding(tmp_path, identity):
    doc = _doc()
    doc["agents"][0]["a2ACard"] = {"url": identity}
    inventory = Inventory.load([_write(tmp_path, doc)])
    assert inventory.entries[0].resources == [K8S_IDENTITY, literal_resource_pattern(identity)]
    assert inventory.match(_finding(identity)) is inventory.entries[0]
    assert inventory.match(_finding("https://agent.example/ab")) is None
    assert inventory.match(_finding("https://agent.example/unapproved")) is None


def test_a2a_card_without_a_url_adds_no_binding(tmp_path):
    doc = _doc()
    doc["agents"][0]["a2ACard"] = {"url": None, "name": "claims"}
    assert Inventory.load([_write(tmp_path, doc)]).entries[0].resources == [K8S_IDENTITY]


@pytest.mark.parametrize("card", ["https://agent.example/card", ["https://agent.example/card"], {"url": ""}])
def test_malformed_a2a_card_fails_closed(tmp_path, card):
    doc = _doc()
    doc["agents"][0]["a2ACard"] = card
    with pytest.raises(InventoryValidationError, match="a2ACard"):
        Inventory.load([_write(tmp_path, doc)])


def test_framework_name_is_lowercased(tmp_path):
    doc = _doc()
    doc["agents"][0]["framework"]["value"]["name"] = "LangGraph"
    assert Inventory.load([_write(tmp_path, doc)]).entries[0].frameworks == ["framework.langgraph"]


# --- Shared load-layer protections, reached through an AgentBOM -----------------


def test_symbolic_links_never_reach_an_agentbom_document(tmp_path):
    outside = tmp_path / "outside"
    outside.mkdir()
    target = _write(outside, _doc())
    link = tmp_path / "link.json"
    link.symlink_to(target)
    with pytest.raises(ValueError, match="symbolic links"):
        Inventory.load([link])
    linked_dir = tmp_path / "linked"
    linked_dir.symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="symbolic links"):
        Inventory.load([linked_dir / "agentbom.json"])
    # A directory walk skips the link and records it rather than loading the document.
    directory = tmp_path / "inventory"
    directory.mkdir()
    (directory / "agentbom.json").symlink_to(target)
    inventory = Inventory.load([directory])
    assert inventory.entries == []
    assert inventory.skipped_links == [str(directory / "agentbom.json")]


@pytest.mark.parametrize("prefix", [b"\xff", b"\xc0\xaf"], ids=["invalid-start-byte", "overlong-sequence"])
def test_non_utf8_bytes_are_refused_before_parsing(tmp_path, prefix):
    path = tmp_path / "agentbom.json"
    path.write_bytes(prefix + json.dumps(_doc()).encode("utf-8"))
    with pytest.raises(InventoryValidationError, match="could not read bounded regular UTF-8 inventory"):
        Inventory.load([path])


@pytest.mark.parametrize("over_by", [0, 1], ids=["exactly-the-limit", "one-byte-over"])
def test_document_size_limit_is_enforced_by_the_bounded_reader(tmp_path, monkeypatch, over_by):
    # files.MAX_POLICY_BYTES is bound into read_policy_text's default when that module is
    # imported, so the reader the registry calls is capped at the document's size instead of
    # writing 8 MiB; the refusal still comes from the real bounded reader.
    path = _write(tmp_path, _doc())
    capped = functools.partial(files.read_policy_text, max_bytes=path.stat().st_size - over_by)
    monkeypatch.setattr("shadowscan.registry.read_policy_text", capped)
    if not over_by:
        assert len(Inventory.load([path]).entries) == 1
        return
    with pytest.raises(InventoryValidationError, match="could not read bounded regular UTF-8 inventory"):
        Inventory.load([path])


def test_deeply_nested_json_never_escapes_the_loader(tmp_path):
    # Whether the strict decoder can read 100,000 nested arrays depends on the interpreter:
    # through 3.13 it raises RecursionError at a fixed depth, while 3.14 bounds recursion by
    # the remaining C stack, so a runner with a deep stack reads the document. Either way the
    # loader must fail closed with an inventory validation error, never let RecursionError
    # escape, and, when it reads the document, yield exactly the subject entry, since the
    # nested value sits under a key the loader does not consume.
    path = tmp_path / "agentbom.json"
    depth = 100_000
    path.write_text(json.dumps(_doc())[:-1] + ', "deepNesting": ' + "[" * depth + "]" * depth + "}")
    try:
        inventory = Inventory.load([path])
    except InventoryValidationError as error:
        assert "invalid syntax" in str(error)
    else:
        assert [entry.agent_id for entry in inventory.entries] == ["agent:claims-assistant"]
        assert inventory.entries[0].resources == [K8S_IDENTITY]


def test_top_level_list_is_not_an_agentbom(tmp_path):
    # Only an object carrying the markers is an AgentBOM: a list of them is read as plain
    # entries, whose field check refuses the document, so the subject never becomes an approval.
    path = tmp_path / "agentbom.json"
    path.write_text(json.dumps([_doc()]))
    with pytest.raises(InventoryValidationError, match="unsupported field"):
        Inventory.load([path])


@pytest.mark.parametrize("marker", ["specVersion", "snapshot", "subject"])
def test_document_missing_one_marker_names_the_missing_marker(tmp_path, marker):
    # Two markers make the document an AgentBOM candidate, so the error names the missing
    # marker instead of steering the operator to delete the others as unsupported fields.
    doc = _doc()
    del doc[marker]
    path = _write(tmp_path, doc)
    expected = (
        f"invalid inventory {path}: document 1.{marker}: "
        "missing; an AgentBOM document requires specVersion, snapshot and subject"
    )
    with pytest.raises(InventoryValidationError) as caught:
        Inventory.load([path])
    assert str(caught.value) == expected


@pytest.mark.parametrize("marker", ["specVersion", "snapshot", "subject"])
def test_document_with_only_one_marker_keeps_the_plain_shape_error(tmp_path, marker):
    # One marker is not enough to read the document as an AgentBOM: the plain ``agents:``
    # shape refuses the extra top-level field, as before, and nothing is approved.
    doc = {"agents": _doc()["agents"], marker: _doc()[marker]}
    with pytest.raises(InventoryValidationError, match="unsupported field; allowed fields: agents"):
        Inventory.load([_write(tmp_path, doc)])


@pytest.mark.parametrize("marker", ["specVersion", "snapshot", "subject"])
def test_document_missing_one_marker_without_agents_names_the_missing_marker(tmp_path, marker):
    # Without ``agents`` the document would otherwise be refused as a simple entry.
    doc = {name: value for name, value in _doc().items() if name in ("specVersion", "snapshot", "subject")}
    del doc[marker]
    with pytest.raises(InventoryValidationError, match=rf"document 1\.{marker}: missing; an AgentBOM"):
        Inventory.load([_write(tmp_path, doc)])


def test_card_with_two_markers_keeps_the_card_shape(tmp_path):
    # A card does not restrict its top-level fields, so two markers alone do not turn a
    # valid card into an invalid AgentBOM.
    doc = {"metadata": {"agent_id": "billing-bot"}, "specVersion": "0.1", "subject": "agent:billing-bot"}
    inventory = Inventory.load([_write(tmp_path, doc)])
    assert [entry.agent_id for entry in inventory.entries] == ["billing-bot"]


# --- Autonomy ladder and snapshot history ----------------------------------------


@pytest.mark.parametrize("name,level", sorted(ISO_TO_LEVEL.items()))
def test_every_iso_automation_level_maps_to_its_shadowscan_level(tmp_path, name, level):
    doc = _doc()
    doc["agents"][0]["automationLevel"]["value"] = name
    assert Inventory.load([_write(tmp_path, doc)]).entries[0].autonomy_level == level


def test_documented_autonomy_table_matches_the_code_mapping():
    text = SYMBIOTE_DOC.read_text(encoding="utf-8")
    section = text.split("## Autonomy vocabulary", 1)[1].split("\n## ", 1)[0]
    documented: dict[str, int] = {}
    names: dict[int, str] = {}
    for line in section.splitlines():
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        row = re.fullmatch(r"L(\d) ([a-z-]+)", cells[-1]) if len(cells) == 2 else None
        if row is None:
            continue
        names[int(row.group(1))] = row.group(2)
        for name in re.findall(r"`([A-Za-z]+)`", cells[0]):
            documented[name] = int(row.group(1))
    assert documented == ISO_TO_LEVEL
    assert names == {entry.number: entry.name for entry in LEVELS}
    assert set(ISO_TO_LEVEL.values()) == {entry.number for entry in LEVELS}


# --- Other SymBiote output formats ------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        # The native AIBOM that current nexus-symbiote builds write from `scan` and
        # `import-shadowscan` (docs/integrations/symbiote.md, Compatibility).
        {"metadata": {"spec_version": "1.0.0"}, "components": [], "dependencies": []},
        {
            "metadata": {"spec_version": "1.0.0", "tool_name": "nexus-symbiote"},
            "components": [{"bom_ref": "agent:a", "component_type": "agent", "name": "a"}],
            "dependencies": [],
        },
        # Its CycloneDX export, bare and with the top-level metadata a real export carries
        # (which routes it through the Capability Card shape), and its SPDX export.
        {"bomFormat": "CycloneDX", "specVersion": "1.7", "version": 1, "components": []},
        {
            "bomFormat": "CycloneDX",
            "specVersion": "1.7",
            "version": 1,
            "metadata": {
                "timestamp": "2026-11-05T00:00:00Z",
                "tools": {"components": [{"type": "application", "name": "nexus-symbiote"}]},
                "component": {"type": "application", "name": "claims-assistant"},
            },
            "components": [],
        },
        {"spdxVersion": "SPDX-2.3", "SPDXID": "SPDXRef-DOCUMENT", "name": "claims-assistant", "packages": []},
    ],
)
def test_symbiote_documents_other_than_agentbom_0_1_are_refused(tmp_path, payload):
    # Regression for the documented compatibility claim: a producer format the loader
    # does not support fails inventory validation instead of loading as an empty inventory.
    with pytest.raises(InventoryValidationError):
        Inventory.load([_write(tmp_path, payload)])


def test_a_newer_agentbom_spec_version_is_refused(tmp_path):
    doc = _doc()
    doc["specVersion"] = "0.2"
    with pytest.raises(InventoryValidationError, match="expected 0.1"):
        Inventory.load([_write(tmp_path, doc)])


def test_two_snapshots_of_one_subject_in_a_directory_approve_nothing(tmp_path):
    # A history directory holds serial 1 and serial 2 of the same agent: both entries bind
    # the workload, and the matcher reports the ambiguity rather than choosing one.
    directory = tmp_path / "boms"
    directory.mkdir()
    (directory / "serial-1.json").write_text(json.dumps(_doc()))
    later = _doc()
    later["snapshot"]["serial"] = 2
    later["snapshot"]["id"] = "snap:2:" + later["snapshot"]["digest"][7:19]
    (directory / "serial-2.json").write_text(json.dumps(later))
    inventory = Inventory.load([directory])
    assert sorted(entry.card["snapshot_serial"] for entry in inventory.entries) == [1, 2]
    finding = _finding(K8S_IDENTITY)
    assert inventory.match(finding) is None
    assert finding.metadata["registry_match_reason"] == "ambiguous-resource-approval"
    assert finding.metadata["registry_suggestions"] == ["agent:claims-assistant"]
