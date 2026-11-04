# Security alert triage — October 18, 2026

This records the scope review of alerts read on 2026-10-18 and the three
path-specific dispositions applied after review. It does not establish that
the repository has no other vulnerabilities or replace review of later findings. The Scorecard alerts
below describe its analysis of commit `44ff47267a5d7d9a331f6d7fb5231b611705a844`;
the current ruleset readback is separate evidence.

| Alert | Evidence and disposition |
|---|---|
| [Dependabot #1](https://github.com/aisecnomad/Nexus-ShadowScan/security/dependabot/1), `ai` / GHSA-rwvc-j5jr-mgvh | The affected `ai: ^4.3.0` declaration is in [`benchmarks/shadowbench/estate/artifacts/code/repo-support-bot-ts/package.json`](https://github.com/aisecnomad/Nexus-ShadowScan/blob/0792106b8d2cc09517f7f4ee2eeabf4f8eb8da2d/benchmarks/shadowbench/estate/artifacts/code/repo-support-bot-ts/package.json), a frozen synthetic input. The vulnerable version range is real, but this is test data, not a ShadowScan runtime dependency. Dismissed as `not_used` on October 18 with a path-specific static-input rationale; changing a frozen artifact merely to clear the alert would change the benchmark. |
| [Scorecard #39](https://github.com/aisecnomad/Nexus-ShadowScan/security/code-scanning/39) and [#41](https://github.com/aisecnomad/Nexus-ShadowScan/security/code-scanning/41), unpinned dependencies | At the reviewed commit, both pointed to [`tests/fixtures/sample_repo/services/support-bot/Dockerfile`](https://github.com/aisecnomad/Nexus-ShadowScan/blob/44ff47267a5d7d9a331f6d7fb5231b611705a844/tests/fixtures/sample_repo/services/support-bot/Dockerfile), lines 1 and 4: an unpinned Node image and npm instruction that the scanner reads as fixture text. The alert instances themselves classify the file as `test`. The production [`Dockerfile`](https://github.com/aisecnomad/Nexus-ShadowScan/blob/main/Dockerfile) is separate, with digest-pinned base images and hash-locked Python installs. Both were dismissed as `used in tests` on October 18 with the fixture/production distinction recorded in each alert. |
| [Scorecard #48](https://github.com/aisecnomad/Nexus-ShadowScan/security/code-scanning/48), no recognized fuzzing integration | The [`Fuzz` workflow](https://github.com/aisecnomad/Nexus-ShadowScan/blob/main/.github/workflows/fuzz.yml) defines three Atheris targets, scheduled and manual runs, and checks on harness changes. Scorecard does not recognize this Python integration; the [fuzzing guide](fuzzing.md#what-it-does-not-show) records that limitation. This alert does not establish an absence of fuzzing. A workflow definition alone also does not prove a recent run passed; inspect the run for the revision in question. |
| [Scorecard #49](https://github.com/aisecnomad/Nexus-ShadowScan/security/code-scanning/49), sampled code reviews | The analysis reports 18 of 28 changesets approved. This is a historical coverage limitation, not fixed by changing current rules or adding a label. Check each selected PR's final revision, review author and eligibility; AI review is not independent human approval. |
| [Scorecard #50](https://github.com/aisecnomad/Nexus-ShadowScan/security/code-scanning/50), no Best Practices badge | No badge is claimed. The [prepared evidence](openssf-best-practices.md) records answers only a developer can attest to; the one MUST criterion it recorded as a gap on October 18 (`crypto_keylength`) is closed as of 2026-10-26 by the RSA modulus bound in `shadowscan/utils/jwks.py` and its regression test. Preparation is not an application or certification; a maintainer must register the project with their own sign-in and truthfully answer the questionnaire. |
| [Scorecard #36](https://github.com/aisecnomad/Nexus-ShadowScan/security/code-scanning/36), non-maximal branch protection | The stated gaps are one required reviewer rather than two, and no required CODEOWNERS review. Those settings are accurate and do not mean the branch is unprotected. The [October 18 readback](merge-policy.md#october-18-readback) shows active rules, no bypass actors, final-push approval and strict required checks. Adding reviewers or CODEOWNERS requirements is a separate governance decision, not a prerequisite for truthfully retaining the current one-review policy. |

The benchmark artifacts and fixture Dockerfile must remain static inputs.
[`AGENTS.md`](https://github.com/aisecnomad/Nexus-ShadowScan/blob/main/AGENTS.md)
prohibits executing the benchmark corpus; package discovery includes only
`shadowscan*`, and the production Docker build context excludes both benchmark
and test trees. If someone adapts a fixture into an application, its dependency
declarations and build instructions need a fresh assessment before use.

Only Dependabot #1 and Code Scanning #39/#41 were dismissed. No repository
settings or blanket suppressions changed. Other alerts retain their existing
status; later dispositions need evidence tied to the exact alert and path.

## October 20 fixture pinning follow-up

The [post-merge Scorecard run](https://github.com/aisecnomad/Nexus-ShadowScan/actions/runs/39444744560)
still scored Pinned-Dependencies 9/10: the fixture's global npm installation
remained unpinned after its Node image had been pinned. The fixture now uses a
verified Node 22-slim multi-platform digest and a separate
[`claude-cli/package-lock.json`](https://github.com/aisecnomad/Nexus-ShadowScan/blob/main/tests/fixtures/sample_repo/services/support-bot/claude-cli/package-lock.json).
It locks `@anthropic-ai/claude-code` 2.1.304 and all eight native optional
packages with exact versions and registry SHA-512 integrity values. Node 22
satisfies that package's declared `>=22.0.0` requirement.

The Dockerfile uses `npm ci --ignore-scripts --engine-strict --no-audit --no-fund`;
no package lifecycle script or CLI is executed. This preserves scanner
dependency evidence, not a promise of an operational Claude installation:
its postinstall is intentionally disabled. The fixture was not built or run.
The historical alert dispositions above remain unchanged. This correction
does not establish a 10/10 score; a new Scorecard run on the merged revision
must verify that outcome.

## November 4 alerts on a removed benchmark manifest

Five Dependabot security-update runs failed on 2026-11-03 (23:58 UTC) and
2026-11-04 (00:31 to 00:34 UTC), all against `main` at `1a821e57`:
[41743229626](https://github.com/Hunzee-VC/Nexus-ShadowScan/actions/runs/41743229626),
[41747503854](https://github.com/Hunzee-VC/Nexus-ShadowScan/actions/runs/41747503854),
[41747537479](https://github.com/Hunzee-VC/Nexus-ShadowScan/actions/runs/41747537479),
[41747673760](https://github.com/Hunzee-VC/Nexus-ShadowScan/actions/runs/41747673760)
and [41747890565](https://github.com/Hunzee-VC/Nexus-ShadowScan/actions/runs/41747890565).
Each was a `security` job for `undici` (advisory range `>= 7.0.0 < 7.30.1`)
in the directory `/tools/benchmark/realworld/cdxgen`, and each ended with the
line

```text
Error during file fetching; aborting: /tools/benchmark/realworld/cdxgen/package.json not found
```

There is no such manifest to fetch. `main` has not contained
`tools/benchmark/realworld/` since
[`05394b79`](https://github.com/Hunzee-VC/Nexus-ShadowScan/commit/05394b79c2a4ad4014fbf03c53a63d6d07f8b3d1)
(#281, 2026-10-20) extracted the benchmark harnesses and corpora, including the
estate artifacts of the Dependabot #1 row above, to the pinned companion. The
dependency graph that Dependabot reads still lists the removed lock: the SBOM
export read on 2026-11-04
(`gh api repos/Hunzee-VC/Nexus-ShadowScan/dependency-graph/sbom`) held 206 npm
entries, among them `undici` 7.29.1 and the `@cdxgen/*` packages of the removed
`tools/benchmark/realworld/cdxgen/package-lock.json`, while none of the
manifests under `tests/fixtures/` that are on `main` appeared.
`.github/dependabot.yml` has never had an npm or Go entry, so nothing refreshes
those parts of the graph; its pip entry keeps the Python part current. Security
updates are alert-driven from the graph, not from that file.

Disposition to apply (not yet applied): in the Security tab's Dependabot
alerts, filter by the manifest
`tools/benchmark/realworld/cdxgen/package-lock.json`, check for any alert
whose manifest is under `benchmarks/shadowbench/estate/artifacts/code/`,
confirm that each manifest path is absent from `main`, and dismiss those
alerts with the reason "This alert is inaccurate or incorrect" (or "Vulnerable
code is not actually used", the October 18 precedent) and the comment
"Manifest removed from main in 05394b79 (#281, 2026-10-20); the dependency
graph still lists it". Record the alert numbers and the date in this section
once that is done. No repository setting changes: the dependency graph and
Dependabot security updates stay enabled, and nothing is suppressed by
pattern.

Verification afterwards: the same SBOM call no longer lists the lock (no
`undici`, `@cyclonedx/cdxgen` or `@cdxgen/*` entries), and the Actions list
shows no new Dependabot run for `/tools/benchmark/realworld/cdxgen` after the
next `undici` advisory. Dependabot is expected to queue a security update only
for an open alert, so dismissal should stop these runs; the Actions check is
what confirms it. Dismissal does not by itself rebuild the graph. If the
export still lists the lock, the entries are stale rather than live, and
rebuilding the graph is a request to GitHub Support; do not record the graph
as rebuilt until the export shows the entries gone.

The rule: an alert on a manifest that is not on `main` is dismissed with this
rationale, naming the commit that removed the manifest. It is never fixed by
re-adding the manifest or by adding an npm or Go entry to
`.github/dependabot.yml`: an entry for a directory that is not on `main` adds
a weekly `package.json not found` failure and refreshes nothing, and a
re-added manifest would be a benchmark input, not a ShadowScan dependency.
