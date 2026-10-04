# Evidence bundles

A `.ggb` file is a deterministic zip that lets anyone check that a GitGrounded result was not edited after it was produced, and, when signed in CI, which workflow at which commit produced it.

## What a valid bundle proves

"Workflow W in repository R at commit C ran GitGrounded version V with config hash H on suite version S with dataset hash D at time T and produced exactly these records and this verdict."

## What it does not prove

* That the suite is fair. Mitigation: the suite, its coverage and mutation score travel inside the bundle, and the suite files are committed in the repository at that commit.
* That the judge is right. Mitigation: deterministic assertions, pairwise judging in both orders, optional judge panels, calibration against human labels, and full transcripts inside the bundle.
* That a local run is a CI run. Local bundles are marked self signed and the verifier says so.

The accurate claim is tamper evident and independently verifiable, not tamper proof.

## Layout

```
manifest.json
records/cases.jsonl
records/transcripts.jsonl
records/judgements.jsonl
records/assertions.jsonl
inputs/config.resolved.json
inputs/change.diff
inputs/suite/current.jsonl
inputs/suite/coverage.json
inputs/suite/mutation.json
summary.json
merkle.json
report.html
signature/local.json or signature/manifest.sigstore.json
```

## Integrity

* Every record is canonical JSON (sorted keys, no whitespace, floats rounded to 6 digits).
* Merkle tree: leaf hash is SHA256(0x00 || line), node hash is SHA256(0x01 || left || right), an odd node is promoted. The root is stored in `manifest.json`.
* `manifest.json` lists the SHA256 of every other file and is itself canonical JSON.
* The signature covers the exact bytes of `manifest.json`.

## Signing

| Mode | When | Strength |
|---|---|---|
| `sigstore` | GitHub Actions with `id-token: write` | certificate bound to the workflow identity, logged in Rekor |
| `local` | developer machine | Ed25519 key in `~/.config/gitgrounded/keys/`, marked self signed |
| `none` | opt out | integrity only |

`sign: auto` picks sigstore in GitHub Actions when available, otherwise local.

The GitHub Action also creates an artifact attestation with predicate type `https://gitgrounded.dev/attestation/eval-run/v1` whose predicate is the manifest.

## Verify

```bash
gitgrounded verify run.ggb
gitgrounded verify run.ggb --identity https://github.com/OWNER/REPO/.github/workflows/gitgrounded.yml@refs/heads/main
gitgrounded verify run.ggb --public-key <key id>
gh attestation verify run.ggb --repo OWNER/REPO
```

Statuses: `VERIFIED`, `VERIFIED_SELF_SIGNED`, `VERIFIED_INTEGRITY_SIGNATURE_PRESENT` (CI signature present, identity not checked), `VERIFIED_UNSIGNED`, `SIGNATURE_INVALID`, `TAMPERED`.

The browser verifier in `verifier/index.html` recomputes every hash and the Merkle root and checks Ed25519 signatures client side. Nothing is uploaded.

## Redaction

Authorization style headers are always replaced by a salted HMAC before records are written. Add JSONPaths under `evidence.redact` to hide more fields. Records stay verifiable because the redaction happens before hashing.
