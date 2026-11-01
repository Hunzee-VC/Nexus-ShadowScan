"""SymBiote AgentBOM documents as an inventory source.

A SymBiote AgentBOM (https://github.com/aisecnomad/SymBiote) is the sealed,
machine-generated bill of materials of one agent. Loading one as inventory
registers its subject agent as sanctioned, with the owner, autonomy level and
discovery resources taken from the document instead of a hand-written card.

Only the fields named below are read; everything else in the document is
ignored here. Parsing is fail-closed in the house style: a malformed document
raises the same validation error family as a malformed card, never a silently
smaller inventory. The document's own assurance semantics are respected: an
``automationLevel`` claim whose ``state`` is not ``present`` contributes no
declared level (unknown never counts as low).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

#: Top-level keys that identify an AgentBOM companion document.
AGENTBOM_MARKERS = ("specVersion", "snapshot", "subject")

#: ISO/IEC 22989 automation ladder (SPDX 3.1 ``isoAutomationLevel`` names) to
#: the L0-L5 scale of :mod:`shadowscan.autonomy`.
ISO_TO_LEVEL: dict[str, int] = {
    "notAutomated": 0,
    "assistiveAutomation": 1,
    "partialAutomation": 2,
    "conditionalAutomation": 3,
    "highAutomation": 4,
    "fullAutomation": 5,
    "autonomous": 5,
}


def is_agentbom(doc: Any) -> bool:
    """Whether ``doc`` looks like an AgentBOM companion document (checked before
    the plain ``agents:`` inventory shape, which an AgentBOM also contains)."""
    return isinstance(doc, dict) and all(marker in doc for marker in AGENTBOM_MARKERS)


def _claim_value(claim: Any) -> Any:
    """The value of a serialized SymBiote claim, or ``None`` when absent/unknown."""
    if not isinstance(claim, dict):
        return None
    if claim.get("state") not in (None, "present"):
        return None
    return claim.get("value")


def _strings(values: Any) -> list[str]:
    if not isinstance(values, list):
        return []
    return [v for v in values if isinstance(v, str) and v]


def summarize(doc: dict[str, Any], path: Path, location: str, invalid: Any) -> dict[str, Any]:
    """Extract the inventory-relevant facts of one AgentBOM document.

    ``invalid`` is :func:`shadowscan.registry._invalid`, passed in to keep this
    module import-light and the error type single-sourced. The return value is
    the keyword set of an ``InventoryEntry`` minus ``source``.
    """
    subject = doc.get("subject")
    if not isinstance(subject, str) or not subject:
        raise invalid(path, f"{location}.subject", "a nonempty string is required")
    snapshot = doc.get("snapshot")
    if not isinstance(snapshot, dict) or not str(snapshot.get("digest", "")).startswith("sha256:"):
        raise invalid(path, f"{location}.snapshot.digest", "a sha256: digest is required")
    agents = doc.get("agents")
    if not isinstance(agents, list):
        raise invalid(path, f"{location}.agents", "expected the document's agent entities")
    agent = next((a for a in agents if isinstance(a, dict) and a.get("id") == subject), None)
    if agent is None:
        raise invalid(path, f"{location}.agents", f"subject {subject!r} is not among the agents")

    parties = {p.get("id"): p for p in doc.get("parties", []) if isinstance(p, dict)}
    owner = None
    owner_party = parties.get(agent.get("ownerRef"))
    if isinstance(owner_party, dict) and isinstance(owner_party.get("name"), str):
        owner = owner_party["name"]

    level: int | None = None
    ladder = _claim_value(agent.get("automationLevel"))
    if ladder is not None:
        if not isinstance(ladder, str) or ladder not in ISO_TO_LEVEL:
            raise invalid(
                path,
                f"{location}.agents.{subject}.automationLevel",
                "expected an isoAutomationLevel name",
            )
        level = ISO_TO_LEVEL[ladder]

    names = [subject.split(":", 1)[-1]]
    if isinstance(agent.get("name"), str) and agent["name"]:
        names.append(agent["name"])

    frameworks: list[str] = []
    framework = _claim_value(agent.get("framework"))
    if isinstance(framework, dict) and isinstance(framework.get("name"), str):
        frameworks.append(f"framework.{framework['name'].strip().lower()}")

    resources: list[str] = []
    for deployment in doc.get("deployments", []):
        if not isinstance(deployment, dict) or deployment.get("agentRef") != subject:
            continue
        workload = deployment.get("workloadRef")
        if isinstance(workload, dict):
            uid = workload.get("uid")
            if isinstance(uid, str) and uid:
                resources.append(uid)
            namespace, name = workload.get("namespace"), workload.get("name")
            if isinstance(namespace, str) and isinstance(name, str) and namespace and name:
                resources.append(f"k8s:{namespace}/{name}")
    for server in doc.get("toolServers", []):
        if not isinstance(server, dict):
            continue
        endpoint = _claim_value(server.get("endpoint"))
        if isinstance(endpoint, str) and endpoint:
            resources.append(endpoint)
        package = _claim_value(server.get("package"))
        if isinstance(package, dict) and isinstance(package.get("purl"), str) and package["purl"]:
            resources.append(package["purl"])
    for ref in agent.get("externalRefs", []) or []:
        if isinstance(ref, dict) and isinstance(ref.get("url"), str) and ref["url"]:
            resources.append(ref["url"])
    card_url = None
    a2a = agent.get("a2ACard")
    if isinstance(a2a, dict) and isinstance(a2a.get("url"), str) and a2a["url"]:
        card_url = a2a["url"]
        resources.append(card_url)

    return {
        "agent_id": subject,
        "name": agent.get("name") if isinstance(agent.get("name"), str) else None,
        "owner": owner,
        "resources": _strings(resources),
        "names": _strings(names),
        "frameworks": frameworks,
        "tags": ["agentbom"],
        "autonomy_level": level,
        "card": {
            "schema": "symbiote-agentbom",
            "spec_version": str(doc.get("specVersion", "")),
            "snapshot_id": str(snapshot.get("id", "")),
            "snapshot_digest": str(snapshot.get("digest", "")),
            "snapshot_serial": snapshot.get("serial"),
        },
    }


__all__ = ["AGENTBOM_MARKERS", "ISO_TO_LEVEL", "is_agentbom", "summarize"]
