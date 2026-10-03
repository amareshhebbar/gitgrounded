import json
from pathlib import Path
from typing import Any

from gitgrounded.cases.loader import load_cases
from gitgrounded.cases.model import Case
from gitgrounded.config.schema import ProviderCfg
from gitgrounded.judges.rubric import RubricJudge, load_rubric
from gitgrounded.stats.reliability import cohen_kappa, spearman
from gitgrounded.store.cache import Cache
from gitgrounded.targets.base import Transcript


def load_labels(path: Path) -> list[dict[str, Any]]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def calibrate(
    labels_path: Path,
    rubric_name: str,
    judge_cfg: ProviderCfg,
    cache: Cache,
    base_dir: Path,
    pass_threshold: float = 6.0,
) -> dict[str, Any]:
    rows = load_labels(labels_path)
    rubric = load_rubric(rubric_name, base_dir)
    judge = RubricJudge(rubric, judge_cfg, cache)
    human_scores, judge_scores, human_pass, judge_pass = [], [], [], []
    details = []
    for i, row in enumerate(rows):
        case_data = row.get("case") or {
            "id": row.get("id", f"label-{i}"),
            "input": row["input"],
            "expectations": row.get("expectations", []),
        }
        case = Case.model_validate(case_data)
        tr = Transcript(
            case_id=case.id,
            variant="label",
            trial=0,
            request={},
            raw_output=row["output"] if isinstance(row["output"], str) else json.dumps(row["output"]),
            output=row["output"],
        )
        jr = judge.evaluate(case, tr, row.get("context", ""))
        hs = row.get("score")
        hp = row.get("pass")
        if hs is not None:
            human_scores.append(float(hs))
            judge_scores.append(jr.score)
        if hp is not None:
            human_pass.append(bool(hp))
            judge_pass.append(jr.score >= pass_threshold)
        details.append({"id": case.id, "human_score": hs, "human_pass": hp, "judge_score": jr.score})
    return {
        "labels": len(rows),
        "rubric": rubric.name,
        "rubric_hash": rubric.hash(),
        "judge": judge_cfg.model_dump(mode="json"),
        "spearman": spearman(human_scores, judge_scores),
        "cohen_kappa_pass": cohen_kappa(human_pass, judge_pass),
        "pass_agreement": (sum(1 for a, b in zip(human_pass, judge_pass) if a == b) / len(human_pass))
        if human_pass
        else None,
        "pass_threshold": pass_threshold,
        "details": details,
    }


__all__ = ["calibrate", "load_cases"]
