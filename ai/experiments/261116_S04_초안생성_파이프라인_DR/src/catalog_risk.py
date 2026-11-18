"""위험도 계산을 팀 백엔드 정책 CATALOG-MVP-1.0으로 한다(팀 결정 2026-11-17).

- 계산 함수는 SafeT 저장소의 backend/domain/risk_policy.py를 그대로 불러 쓴다(로직 복제 없음).
- 카탈로그는 SafeT 저장소의 contracts/catalog_risk/catalog.json을 읽는다.
- 후보 → 카탈로그 시나리오 연결은 백엔드 generate()와 같은 키워드 포함 규칙을 쓴다. 최종 선택은 사용자가 한다.
- 결과 형식은 계약 v2.1 risk_result(261115_AI출력계약_신호기준_DR/schemas_v2_1).

저장소 위치: 환경변수 SAFET_REPO → 이 파일 위쪽 폴더 중 contracts/catalog_risk가 있는 곳 → Final_Project/SafeT.
자체 시험: python src/catalog_risk.py  → runs/hitl_recommend/catalog_risk_check.json
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve()
CATALOG_REL = Path("contracts/catalog_risk/catalog.json")
POLICY_REL = Path("backend/domain/risk_policy.py")


def find_repo() -> Path:
    cands = [Path(os.environ["SAFET_REPO"])] if os.environ.get("SAFET_REPO") else []
    cands += list(HERE.parents)
    cands += [p / "SafeT" for p in HERE.parents]
    for c in cands:
        if (c / CATALOG_REL).is_file() and (c / POLICY_REL).is_file():
            return c
    raise FileNotFoundError("SafeT 저장소(contracts/catalog_risk, backend/domain/risk_policy.py)를 찾지 못함. SAFET_REPO를 지정하세요.")


class CatalogRisk:
    def __init__(self, repo: Path | None = None):
        self.repo = repo or find_repo()
        spec = importlib.util.spec_from_file_location("safet_risk_policy", self.repo / POLICY_REL)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.evaluate, self.policy = mod.evaluate, mod.POLICY
        data = json.loads((self.repo / CATALOG_REL).read_text(encoding="utf-8"))
        assert data["policy_version"] == self.policy, (data["policy_version"], self.policy)
        self.scenarios = {s["id"]: s for s in data["scenarios"]}

    # ---------------------------------------------------------------- 연결
    def match(self, *texts: str) -> list[str]:
        """백엔드 generate()와 같은 규칙: 시나리오 keywords 중 하나라도 문장에 들어 있으면 후보."""
        q = " ".join(t for t in texts if t).lower()
        return [sid for sid, s in self.scenarios.items() if any(k.lower() in q for k in s["keywords"])]

    def controls(self, sid: str) -> list[dict]:
        return [{"id": c["id"], "critical": c["critical"], "current_text": c["current_text"]} for c in self.scenarios[sid]["controls"]]

    # ---------------------------------------------------------------- 계산
    def compute(self, assessment_id: str, selections: list[dict], computed_at: str) -> dict:
        """selections: 계약 v2.1 user_selection.selections. 현재(current)와, 계획 조치가 있으면 예상(expected)을 낸다."""
        out = []
        for x in selections:
            sid = x.get("catalog_scenario_id")
            if not sid:
                out.append({"selection_id": x["selection_id"], "phase": "current", "status": "not_in_catalog",
                            "catalog_scenario_id": None, "severity": None, "control_band": None, "grade": None, "signal": "N",
                            "reason": "카탈로그에 없는 위험입니다. 판단이 필요합니다."})
                continue
            bad = self.input_errors(x)
            if bad:   # 모순·잘못된 입력은 계산하지 않는다(그래프는 이 전에 다시 선택을 요청한다)
                out.append({"selection_id": x["selection_id"], "phase": "current", "status": "needs_information",
                            "catalog_scenario_id": sid if sid in self.scenarios else None, "severity": None,
                            "control_band": None, "grade": None, "signal": "N",
                            "reason": "입력을 다시 확인해야 합니다. " + " ".join(bad)})
                continue
            scn = self.scenarios[sid]
            cur = set(x["current_control_ids"])
            answered = bool(x["no_current_controls"]) or bool(cur)
            r = self.evaluate(scn, cur, answered=answered)
            out.append(self._row(x["selection_id"], "current", sid, r))
            plan = set(x["plan_control_ids"])
            if answered and plan:
                e = self.evaluate(scn, cur | plan, answered=True)
                e["reason"] = "선택한 개선대책을 이행한다고 가정한 예상 결과입니다. " + e["reason"]
                out.append(self._row(x["selection_id"], "expected", sid, e))
        return {"assessment_id": assessment_id, "computed_by": "backend_risk_policy", "policy_version": self.policy,
                "computed_at": computed_at, "results": out}

    def input_errors(self, x: dict) -> list[str]:
        """계산 전 입력 검사: 없는 시나리오·조치, '현재 조치 없음'과 현재 조치 동시 선택, 현재·계획 중복."""
        sid = x.get("catalog_scenario_id")
        if sid not in self.scenarios:
            return [f"카탈로그에 없는 위험 상황입니다({sid})."]
        cur, plan = set(x.get("current_control_ids") or []), set(x.get("plan_control_ids") or [])
        known = {c["id"] for c in self.scenarios[sid]["controls"]}
        errs = []
        if (cur | plan) - known:
            errs.append("이 위험 상황에 없는 조치가 있습니다.")
        if x.get("no_current_controls") and cur:
            errs.append("'현재 조치 없음'과 현재 조치를 함께 골랐습니다.")
        if cur & plan:
            errs.append("같은 조치를 현재 조치와 개선 계획에 함께 골랐습니다.")
        return errs

    @staticmethod
    def _row(sel_id, phase, sid, r):
        return {"selection_id": sel_id, "phase": phase,
                "status": r["status"], "catalog_scenario_id": sid,
                "severity": r["severity"], "control_band": r["control_band"], "grade": r["grade"], "signal": r["signal"],
                "reason": r["reason"]}


def selftest() -> dict:
    cr = CatalogRisk()
    env = cr.scenarios["ENV"]
    crit = [c["id"] for c in env["controls"] if c["critical"]]
    allc = [c["id"] for c in env["controls"]]
    sels = [
        {"selection_id": "t1", "catalog_scenario_id": "ENV", "current_control_ids": crit[:1], "no_current_controls": False, "plan_control_ids": crit[1:]},
        {"selection_id": "t2", "catalog_scenario_id": "ENV", "current_control_ids": [], "no_current_controls": False, "plan_control_ids": []},
        {"selection_id": "t3", "catalog_scenario_id": "ENV", "current_control_ids": allc, "no_current_controls": False, "plan_control_ids": []},
        {"selection_id": "t4", "catalog_scenario_id": None, "current_control_ids": [], "no_current_controls": True, "plan_control_ids": []},
        # 잘못된 입력: 계산하지 않고 needs_information
        {"selection_id": "t5", "catalog_scenario_id": "ENV", "current_control_ids": crit[:1], "no_current_controls": True, "plan_control_ids": []},
        {"selection_id": "t6", "catalog_scenario_id": "ENV", "current_control_ids": crit[:1], "no_current_controls": False, "plan_control_ids": crit[:1]},
        {"selection_id": "t7", "catalog_scenario_id": "NOPE", "current_control_ids": [], "no_current_controls": True, "plan_control_ids": []},
    ]
    rr = cr.compute("A-SELFTEST", sels, "2026-11-17T00:00:00+09:00")
    got = [(r["selection_id"], r["phase"], r["status"], r["control_band"], r["grade"], r["signal"]) for r in rr["results"]]
    want = [("t1", "current", "calculated", 3, "상", "R"), ("t1", "expected", "calculated", 2, "중", "Y"),
            ("t2", "current", "needs_information", None, None, "N"),
            ("t3", "current", "calculated", 1, "중", "Y"),
            ("t4", "current", "not_in_catalog", None, None, "N"),
            ("t5", "current", "needs_information", None, None, "N"),
            ("t6", "current", "needs_information", None, None, "N"),
            ("t7", "current", "needs_information", None, None, "N")]
    m = {"튀김기 고온 기름 화상": cr.match("튀김기", "기름 교체 중 고온 기름이 튐"),
         "냉장고 앞 바닥 미끄러짐": cr.match("냉장고", "바닥이 미끄러워 넘어짐"),
         "염지기 손 끼임": cr.match("염지기", "회전부 청소 중 손 끼임")}
    return {"repo": str(cr.repo.name), "policy": cr.policy, "scenarios": len(cr.scenarios), "results": got, "pass": got == want,
            "match_examples": m, "note": "ENV 피해 S2. 키워드 포함 규칙은 넓게 잡힌다(예: 청소→VENT, 기름→ENV). 그래서 연결은 후보로만 보이고 시나리오는 사용자가 고른다."}


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    res = selftest()
    out = HERE.parents[1] / "runs" / "hitl_recommend" / "catalog_risk_check.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(res, ensure_ascii=False, indent=1))
    sys.exit(0 if res["pass"] else 1)
