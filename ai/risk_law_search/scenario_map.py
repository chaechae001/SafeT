"""위험사례 카드 → 위험도 시나리오(contracts/catalog_risk/catalog.json) 후보 연결.

  python -m ai.risk_law_search.scenario_map            # card_scenario_map.json 생성(새 파일만)
  python -m ai.risk_law_search.scenario_map --update   # 후보만 다시 계산, 담당자 확정(confirmed)은 보존

- 위험도 계산(backend/domain/risk_policy.py, CATALOG-MVP-1.1)은 시나리오의 피해 수준(severity)과
  핵심·보완 조치(controls)를 쓴다. 우리 모듈은 카드 단위라 카드마다 시나리오가 필요하다.
- 후보: 카드 고유 문구와 시나리오 문구(제목·작업·사고 유형·시나리오·키워드)의 키워드 점수 상위 3개.
  사고 유형 가산점은 쓰지 않는다(카탈로그 사고 유형 이름이 카드와 달라 일부가 나빠졌다).
- 자동 후보는 검토 전 초안이다. 피해 수준이 그대로 위험도에 들어가므로 담당자가 confirmed를 채운다.
  confirmed: null(미검토) | "<시나리오 ID>" | "none"(맞는 시나리오 없음)
"""
import argparse
import json
from pathlib import Path

from backend.domain.risk_policy import RESTAURANT_POLICY, evaluate

from .cards import card_search_text
from .textindex import TextIndex

HERE = Path(__file__).resolve().parent
CATALOG = HERE.parents[1] / "contracts" / "catalog_risk" / "catalog.json"
MAP = HERE / "card_scenario_map.json"
TOP = 3
WEAK = 0.2  # 1순위 점수가 이보다 낮으면 '약한 후보'로 표시(예시 카드에서 오연결이 0.14~0.17)


def scenario_text(s):
    return " ".join([s["title"], s["task"], s["event"], s["scenario"], " ".join(s["keywords"])])


def load_catalog(path=CATALOG):
    catalog = json.loads(Path(path).read_text(encoding="utf-8"))
    catalog["policy_version"] = RESTAURANT_POLICY
    for scenario in catalog["scenarios"]:
        scenario["policy_version"] = RESTAURANT_POLICY
        if scenario["id"] == "FRY":
            # 기름 튐과 직접 연결된 예방·보호 항목. 화재 대응은 FIRE에서 평가한다.
            direct = {"FRY-C1", "FRY-C2", "FRY-C3", "FRY-C7"}
            scenario["controls"] = [c for c in scenario["controls"] if c["id"] in direct]
        scenario["initial_grade"] = evaluate(scenario, [], answered=True)["grade"]
    return catalog


def candidates(engine, catalog):
    sc = catalog["scenarios"]
    idx = TextIndex([scenario_text(s) for s in sc], engine.tokenizer)
    out = {}
    for c in engine.search_cards:
        scores = idx.scores(card_search_text(c))
        top = sorted(scores.items(), key=lambda x: (-x[1], x[0]))[:TOP]
        out[c["id"]] = [dict(scenario_id=sc[i]["id"], title=sc[i]["title"], score=round(v, 3)) for i, v in top]
    return out


def build(engine, path=MAP, update=False, catalog_path=CATALOG):
    if Path(path).exists() and not update:
        raise SystemExit(f"{path} 이미 있음(덮어쓰지 않음). 후보만 다시 계산하려면 --update")
    catalog = load_catalog(catalog_path)
    old = json.loads(Path(path).read_text(encoding="utf-8"))["cards"] if update and Path(path).exists() else {}
    cand = candidates(engine, catalog)
    cards = {c["id"]: dict(title=c["title"], risk_type=c["risk_type"], candidates=cand[c["id"]],
                           confirmed=old.get(c["id"], {}).get("confirmed"), note=old.get(c["id"], {}).get("note", ""))
             for c in engine.search_cards}
    doc = {"_note": "카드 → 위험도 시나리오 연결. candidates는 키워드 자동 후보(검토 전 초안). "
                    "담당자가 confirmed에 시나리오 ID 또는 'none'을 적는다. 비어 있으면 화면에 '자동 후보 · 검토 전'으로 표시된다.",
           "catalog_policy": catalog["policy_version"], "weak_below": WEAK, "cards": cards}
    Path(path).write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return doc


class ScenarioLinker:
    """카드 ID → 위험도 시나리오(피해 수준·조치 기준 포함). 등급 계산은 하지 않는다."""

    def __init__(self, catalog_path=CATALOG, map_path=MAP):
        self.catalog = load_catalog(catalog_path)
        self.by_id = {s["id"]: s for s in self.catalog["scenarios"]}
        self.map = json.loads(Path(map_path).read_text(encoding="utf-8"))["cards"] if Path(map_path).exists() else {}

    def for_card(self, card_id):
        entry = self.map.get(card_id)
        if not entry:
            return dict(status="unmapped", message="시나리오 연결표에 없는 카드입니다 · 담당자 확인 필요")
        confirmed, cands = entry.get("confirmed"), entry.get("candidates") or []
        if confirmed == "none":
            return dict(status="no_scenario", message="담당자 확인: 맞는 시나리오 없음", candidates=cands)
        if confirmed:
            sid, status, msg = confirmed, "confirmed", "담당자 확인"
        elif cands:
            sid = cands[0]["scenario_id"]
            weak = cands[0]["score"] < WEAK
            status = "auto_weak" if weak else "auto"
            msg = "자동 후보(약함) · 검토 필요" if weak else "자동 후보 · 검토 전"
        else:
            return dict(status="unmapped", message="후보 없음 · 담당자 확인 필요")
        s = self.by_id.get(sid)
        if not s:
            return dict(status="invalid", message=f"카탈로그에 없는 시나리오 ID: {sid}", candidates=cands)
        return dict(status=status, message=msg, scenario_id=s["id"], title=s["title"], scenario=s["scenario"],
                    policy_version=s["policy_version"], severity=s["severity"], severity_reason=s.get("severity_reason"),
                    controls=[dict(id=c["id"], critical=c["critical"], current_text=c["current_text"], plan_text=c["plan_text"])
                              for c in s["controls"]],
                    candidates=cands)

    def info(self):
        n = len(self.map)
        confirmed = sum(1 for v in self.map.values() if v.get("confirmed"))
        return dict(catalog_policy=self.catalog["policy_version"], scenarios=len(self.by_id), mapped_cards=n,
                    confirmed_cards=confirmed)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--update", action="store_true")
    ap.add_argument("--data", default=str(HERE.parents[1] / "docs" / "chroma"))
    a = ap.parse_args()
    from .engine import Engine
    eng = Engine(a.data, mode="keyword", log=lambda m: None)
    doc = build(eng, update=a.update)
    weak = sum(1 for v in doc["cards"].values() if v["candidates"] and v["candidates"][0]["score"] < WEAK)
    print(f"저장: {MAP} (카드 {len(doc['cards'])}개, 약한 후보 {weak}개, 담당자 확정 "
          f"{sum(1 for v in doc['cards'].values() if v['confirmed'])}개)")


if __name__ == "__main__":
    main()
