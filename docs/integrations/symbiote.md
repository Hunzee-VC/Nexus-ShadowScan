# SymBiote (AgentBOM) integration

[Nexus SymBiote](https://github.com/Hunzee-VC/Nexus-Symbiote) describes one
agent as a bill of materials: the MCP servers, models, instructions, retrieval
sources, A2A cards and other components the agent is assembled from. ShadowScan
reads one such format, the AgentBOM 0.1 document; current SymBiote builds write
a different one (see [Compatibility](#compatibility)). ShadowScan and SymBiote
split one governance loop:

| Question | Tool |
|---|---|
| What agents exist across the estate, who owns them, are they inventoried? | ShadowScan |
| What exactly is *this* agent made of and permitted to do, and what evidence records it? | SymBiote |

## Compatibility

This page was checked against Nexus SymBiote commit
[`18e4b441`](https://github.com/Hunzee-VC/Nexus-Symbiote/tree/18e4b441bc78268db990d904f85e2ba8af9d9a52),
package `nexus-symbiote` version 0.1.0. Its console command is
`nexus-symbiote`. At that commit it provides `scan`, `import-shadowscan`,
`verify-artifact`, `verify-discovery`, `validate`, `risk`, `diff`, `summary`,
`blast-radius`, `init`, `baseline`, `vex`, `advisories`, `verify-live`,
`discover-mcp` and the `runtime` group (`keygen`, `sign`, `verify`). It has no
`export` command. The companion is alpha and its interfaces may change, so
check the command list of the commit you install.

ShadowScan accepts AgentBOM documents with `specVersion: "0.1"` and no other
version. That is the format of the test fixture
`tests/fixtures/symbiote/agentbom.claims-assistant.json`, whose `producer`
field names `symbiote` version 0.1.0: a Merkle-committed bill of materials with
per-claim assurance and tool-descriptor digests.

The checked commit does not write that format. Its `scan` and
`import-shadowscan` commands write a native AIBOM document
(`metadata.spec_version: "1.0.0"` with `components` and `dependencies` lists)
or a CycloneDX, SPDX or SARIF export. None of these has the top-level
`specVersion`, `snapshot` and `subject` fields of an AgentBOM 0.1 document.
`--inventory` refuses such a file with an inventory validation error (exit 1);
it never reads it as an empty inventory. A newer producer format is not
accepted until the loader in `shadowscan/agentbom.py` supports it.

## AgentBOM documents as inventory

Importing an AgentBOM is an explicit **operator trust decision**, like importing
a Capability Card. Verify the document with the SymBiote build that produced it
(the checked commit has no reader or verifier for AgentBOM 0.1, so a document's
provenance rests on the producing build and on your review) and review the
subject identities before passing its JSON (or a directory of
documents) to `--inventory`. A seal or producer claim alone never approves an
agent:

```bash
shadowscan inventory check boms/      # structural check of AgentBOM 0.1 documents
shadowscan scan -c shadowscan.yaml --inventory boms/
```

Here `boms/` holds AgentBOM 0.1 documents. Older Nexus AIBOM documents and the
native AIBOM that `nexus-symbiote scan` writes are different formats (see
[Compatibility](#compatibility)).

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

AgentBOM 0.1 records autonomy on the ISO/IEC 22989 ladder (the SPDX 3.1
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

The outbound path, exporting a *scan* as CycloneDX for BOM pipelines, is
[`--format cyclonedx`](../operations/ai-bom.md) and is unchanged by this
integration.

## The other direction

ShadowScan reports reach SymBiote through `nexus-symbiote import-shadowscan`.
At the checked commit it reads a ShadowScan native JSON report or a CycloneDX
1.6 or 1.7 report and writes a native AIBOM of declared, unverified claims
(`--format json`, the default, or `cyclonedx` or `spdx`; it refuses `sarif`) to
an output path that must not already exist:

```bash
shadowscan code /path/to/repository --format json -o shadowscan.json
nexus-symbiote import-shadowscan shadowscan.json -o agentbom.json --report-only
nexus-symbiote verify-discovery agentbom.json shadowscan.json
```

Without `--report-only`, `import-shadowscan` exits nonzero after it writes the
file, because imported claims do not establish complete verified coverage.
Without further options, `verify-discovery` compares the report bytes with the
digest the AIBOM records and authenticates neither file. With `--bundle`,
`--signer-identity` and `--issuer` it also verifies the report producer's
Sigstore signature, and `--projection` rebuilds and compares the direct import. The companion's
[ShadowScan integration guide](https://github.com/Hunzee-VC/Nexus-Symbiote/blob/18e4b441bc78268db990d904f85e2ba8af9d9a52/docs/shadowscan-integration.md)
describes the mapping.

At the checked commit SymBiote has no command that writes Agent Capability
Cards, `agents.yaml` lists or AgentBOM 0.1 documents for ShadowScan, and its
native AIBOM is not a ShadowScan inventory. Until a producer writes a supported
format, keep the sanctioned inventory as Capability Cards, an `agents.yaml` list
or CSV ([inventory](../inventory.md)).

## Planned next (not yet implemented here)

Digest-level reconciliation: checking the MCP tool definitions a scan
observes against the AgentBOM's pinned `tooldef/v1` digests, so a tool whose
description or schema changed after approval is flagged at discovery time,
and cross-referencing `shadowscan diff` drift classes with `nexus-symbiote diff`
delta events. Tracked in
[#334](https://github.com/Hunzee-VC/Nexus-ShadowScan/issues/334).
