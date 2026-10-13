# Attestation predicate: eval-run v1

Predicate type URI: `https://amareshhebbar.github.io/gitgrounded/attestation/eval-run/v1`

The GitGrounded GitHub Action creates a GitHub artifact attestation whose subject is the `.ggb` evidence bundle and whose predicate is the bundle `manifest.json`.

## Predicate fields

| Field | Meaning |
|---|---|
| `bundle_format` | bundle format, currently `ggb/1` |
| `run_id` | identifier of the run |
| `project`, `suite`, `suite_version` | names and version from `gitgrounded.yml` |
| `verdict` | PASS, WARN or FAIL |
| `counts` | case, regression and assertion failure counts |
| `created_at` | UTC timestamp |
| `base`, `head` | names, commit SHAs and content hashes that were compared |
| `config_hash`, `dataset_hash` | hashes of the resolved config and the case set |
| `models_used`, `judge` | models that produced and judged the answers |
| `offline` | true when the run used the offline simulation provider |
| `merkle_root` | root over all canonical records in the bundle |
| `files` | sha256 of every file in the bundle |

## Verifying

```bash
gh attestation verify evidence.ggb --repo OWNER/REPO
gitgrounded verify evidence.ggb --require-signature
```

Offline runs are never attested by the Action.
