"""팀 검토 기준표와 실행 중인 판정기의 출력 일치도를 측정한다."""
from itertools import combinations

from .grading import grade_selection


def measure(linker):
    # 검토 기준표의 열 순서: 핵심 미충족 / 핵심만 충족 / 전체 충족.
    reference = {1: ["중", "하", "하"], 2: ["중", "중", "하"], 3: ["상", "중", "중"]}
    total = matched = 0
    for scenario in linker.by_id.values():
        controls = {c["id"] for c in scenario["controls"]}
        critical = {c["id"] for c in scenario["controls"] if c["critical"]}
        grades = reference[scenario["severity"]]
        for size in range(len(controls) + 1):
            for subset in combinations(sorted(controls), size):
                current = set(subset)
                column = 0 if critical - current else (2 if current == controls else 1)
                body = dict(card_id="test", scenario_id=scenario["id"], current_ids=list(current))
                current_only = grade_selection(linker, body)["expected_risk"]
                body["plan_ids"] = sorted(controls - current)
                projected = grade_selection(linker, body)["expected_risk"]
                matched += current_only == grades[column] and projected == grades[2]
                total += 1
    return dict(matched=matched, total=total, scenarios=len(linker.by_id), reference=reference)
