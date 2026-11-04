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

Importing an AgentBOM is an explicit **operator trust decision**, like importing
a Capability Card. Verify the document with SymBiote and review the subject
identities before passing its JSON (or a directory of documents) to `--inventory`.
A seal or producer claim alone never approves an agent:

The commands below require a SymBiote build with AgentBOM 0.1 and its
ShadowScan bridge commands. Older Nexus AIBOM documents are a different format.

```bash
symbiote scan . -o boms/            # SymBiote: one sealed AgentBOM per agent
shadowscan scan -c shadowscan.yaml --inventory boms/
```

Keep one document per subject in the directory you pass. Two snapshots of the
same agent (serial 1 and serial 2 kept side by side) load as two entries with
identical bindings; the matcher reports their resource as ambiguous and neither
entry approves it. Remove superseded snapshots before scanning.

A document is recognized by its top-level `specVersion`, `snapshot` and
`subject` fields with supported `specVersion: "0.1"`, and contributes **one entry:
the subject agent**. An AgentBOM's `agents` list contains its own entity records,
not inventory entries. The mapping, implemented in `shadowscan/agentbom.py`:

| Inventory field | AgentBOM source |
|---|---|
| `agent_id`, `name`, `names` | `subject` and its agent entity |
| `owner` | the agent's `ownerRef` party |
| `autonomy_level` | the `automationLevel` claim, via the table below |
| `resources` | complete `k8s:<cluster>/<namespace>/<kind>/<name>` deployment identities, subject external refs and A2A card URL; all matched literally |
| `frameworks` | the agent's declared framework (`framework.<name>`, with the name lowercased) |
| `card` | provenance: spec version, snapshot id/digest/serial, `verification: not-verified`, descriptive `component_resources` and `workload_uids` |

The loader checks consumed object/list types, bounded collection sizes, unique
entity IDs, subject membership and snapshot subject/digest/serial/id consistency.
Malformed fields raise an inventory validation error. A missing cluster, namespace,
kind or workload name does not generate a guessed Kubernetes identity. Generated
resource bindings escape glob metacharacters, so a URL containing `*`, `?` or `[`
cannot approve another resource.

Tool-server endpoints and package purls describe dependencies, including shared
and floating components. They stay in `card.component_resources`; they never
inherit the subject's sanctioned status, owner or autonomy. Bare workload UIDs
stay in `card.workload_uids`. Subject names remain review suggestions.

Structural checks do **not** recompute the Merkle tree, authenticate a signer or
verify approval, expiry or deployment acceptance. `card.verification` explicitly
remains `not-verified`, even when snapshot and Merkle headers agree. Supply-chain
verification remains SymBiote's responsibility.

Only a `present` automation claim supplies a declared level. The producer
schema defaults an omitted claim state to `present`; explicit `unknown` and
`absent-verified` claims supply no level, and malformed claim states or values
fail validation. Unknown never counts as low.

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
[#334](https://github.com/Hunzee-VC/Nexus-ShadowScan/issues/334).
