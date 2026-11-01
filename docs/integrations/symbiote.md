# SymBiote (AgentBOM) integration

[SymBiote](https://github.com/aisecnomad/SymBiote) generates, seals and
verifies an **AgentBOM** per agent: a Merkle-committed bill of materials with
per-claim assurance, tool-descriptor digests and declared-vs-observed diffing.
ShadowScan and SymBiote split one governance loop:

| Question | Tool |
|---|---|
| What agents exist across the estate, who owns them, are they inventoried? | ShadowScan |
| What exactly is *this* agent made of and permitted to do, sealed and verified? | SymBiote |

## AgentBOM documents as inventory

Every sealed AgentBOM is a machine-written sanctioned-agent record. Pass the
JSON documents (or a directory of them) straight to `--inventory`:

```bash
symbiote scan . -o boms/            # SymBiote: one sealed AgentBOM per agent
shadowscan scan -c shadowscan.yaml --inventory boms/
```

A document is recognized by its top-level `specVersion`, `snapshot` and
`subject` fields, and contributes **one entry: the subject agent** (an
AgentBOM's `agents` list contains the BOM's own entity records, not inventory
entries). The mapping, implemented in `shadowscan/agentbom.py`:

| Inventory field | AgentBOM source |
|---|---|
| `agent_id`, `name`, `names` | `subject` and its agent entity |
| `owner` | the agent's `ownerRef` party |
| `autonomy_level` | the `automationLevel` claim, via the table below |
| `resources` | deployment workload UID and `k8s:<namespace>/<name>`, remote tool-server endpoints, pinned package purls, the agent's external refs and A2A card URL |
| `frameworks` | the agent's declared framework (`framework.<name>`) |
| `card` | provenance: spec version, snapshot id, digest and serial |

Parsing is fail-closed like every other inventory format: a malformed
document raises a validation error rather than loading a smaller inventory,
and an `automationLevel` claim whose state is not `present` contributes no
declared level — unknown never counts as low.

## Autonomy vocabulary

SymBiote records autonomy on the ISO/IEC 22989 ladder (the SPDX 3.1
`isoAutomationLevel` names); ShadowScan uses L0–L5
([autonomy tiers](../concepts/autonomy.md)):

| `isoAutomationLevel` | ShadowScan level |
|---|---|
| `notAutomated` | L0 chatbot |
| `assistiveAutomation` | L1 copilot |
| `partialAutomation` | L2 supervised |
| `conditionalAutomation` | L3 semi-autonomous |
| `highAutomation` | L4 high-autonomy |
| `fullAutomation`, `autonomous` | L5 fully-autonomous |

As with Capability Cards, the declared level is compared against the scan's
observed floor; a declaration never lowers an observed level.

## Related

The outbound path — exporting a *scan* as CycloneDX for BOM pipelines — is
[`--format cyclonedx`](../operations/ai-bom.md) and is unchanged by this
integration.

## The other direction

SymBiote exports ShadowScan-ready inventories directly (schema-version-2
Agent Capability Cards, including `authorized_tools[].sha256` from its
`tooldef/v1` digests, and `agents.yaml` lists), and imports
`shadowscan --format json` reports as observed evidence. See the SymBiote
repository for `symbiote export shadowscan` and `symbiote import --format
shadowscan`.

## Planned next (not yet implemented here)

Digest-level reconciliation: checking the MCP tool definitions a scan
observes against the AgentBOM's pinned `tooldef/v1` digests, so a tool whose
description or schema changed after approval is flagged at discovery time,
and cross-referencing `shadowscan diff` drift classes with `symbiote diff`
delta events. Tracked in
[#334](https://github.com/aisecnomad/Nexus-ShadowScan/issues/334).
