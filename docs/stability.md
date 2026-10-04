# Stability

From 1.0 these formats follow semantic versioning. Breaking changes need a new major version.

| format | version | where |
|---|---|---|
| `gitgrounded.yml` | `version: 1` | `src/gitgrounded/config/schema.py`, `gitgrounded schema` |
| case JSONL | v1 | `src/gitgrounded/cases/model.py` |
| run result | `schema_version: "1"` | `src/gitgrounded/report/model.py` |
| evidence bundle | `ggb/1` | `src/gitgrounded/evidence/bundle.py` |
| certificate bundle | `ggb-cert/1` | `src/gitgrounded/evidence/certify.py` |

Deprecation policy: a deprecated option or command keeps working for one minor release and prints a warning. The legacy hackathon flags (`--old`, `--new`, `--check`, `--compare`, `--labels`, `--del-v`) were removed in 0.2 and now print the replacement command.
