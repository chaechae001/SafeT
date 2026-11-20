"""카드 대책 → 위험도 시나리오 기준 조치(controls) 후보 연결.

  python -m ai.risk_law_search.control_map            # measure_control_map.json 생성(새 파일만)
  python -m ai.risk_law_search.control_map --update   # 후보만 다시 계산, 검토 팀원 확정(confirmed)은 보존

- 서비스 위험도(backend/domain/risk_policy.py, CATALOG-MVP-1.1)는 시나리오 기준 조치 ID의 충족 여부로 계산한다.
  화면의 추천 대책은 카드 대책 문장이라, 체크했을 때 어느 기준 조치를 충족한 것인지 이 표로 정한다.
- 기준 조치는 서비스 DB와 같은 원본(contracts/catalog_risk/catalog.json)을 그대로 쓴다. 모듈 시험용 정책 변경을 반영하지 않는다.
- 후보: 카드 대책 문장과 그 시나리오의 기준 조치 문구의 키워드 점수 1순위. LINK 미만이면 연결하지 않는다.
  연결되지 않은 대책은 저장되지만 위험도 하향 계산에는 쓰지 않는다(직접 추가 대책과 같음).
- 자동 후보는 검토 전 초안이다. confirmed: null(미검토) | "<조치 ID>" | "none"(맞는 기준 조치 없음)
- 위험도 계산에는 기본적으로 confirmed만 쓴다. 자동 후보까지 쓰려면 count_auto=True(서버 --count-auto-controls, 시험용).
"""
import argparse
import json
import re
from pathlib import Path

from .textindex import TextIndex

HERE = Path(__file__).resolve().parent
CATALOG = HERE.parents[1] / "contracts" / "catalog_risk" / "catalog.json"
MAP = HERE / "measure_control_map.json"
LINK = 0.45  # 이 점수 미만은 후보도 두지 않는다. 0.45 이상에서도 오연결이 있어(예: 스마트폰 사용 금지 → 운전 전 점검)
#              자동 후보는 기본적으로 위험도 계산에 쓰지 않는다(ControlMapper.count_auto).


def norm(text):
    return re.sub(r"\s+", " ", text or "").strip()


def key(scenario_id, original):
    return f"{scenario_id}|{norm(original)}"


def load_raw_catalog(path=CATALOG):
    return json.loads(Path(path).read_text(encoding="utf-8"))


class ControlIndex:
    def __init__(self, catalog, tokenizer):
        self.rows = [(s["id"], c) for s in catalog["scenarios"] for c in s["controls"]]
        self.index = TextIndex([f"{c['current_text']} {c['plan_text']}" for _, c in self.rows], tokenizer)
        self.by_scenario = {}
        for i, (sid, _) in enumerate(self.rows):
            self.by_scenario.setdefault(sid, set()).add(i)

    def best(self, scenario_id, text):
        allowed = self.by_scenario.get(scenario_id)
        if not allowed:
            return None, 0.0
        scores = self.index.scores(text, allowed)
        if not scores:
            return None, 0.0
        i, v = max(scores.items(), key=lambda x: (x[1], -x[0]))
        return self.rows[i][1]["id"], round(v, 3)


def pool(engine, card):
    """analyze가 이 카드에 보여 줄 수 있는 대책 문장 전체(이 카드·유사 카드의 직접·보강 대책)."""
    cards = [card] + [engine.card_by_id[x] for x in engine.similar.get(card["id"], [])]
    out = []
    for c in cards:
        out += list(c["measures"]) + [m["text"] for m in c["measures_extra"]]
    return [norm(t) for t in out if norm(t)]


def build(engine, linker, path=MAP, update=False, catalog_path=CATALOG):
    if Path(path).exists() and not update:
        raise SystemExit(f"{path} 이미 있음(덮어쓰지 않음). 후보만 다시 계산하려면 --update")
    catalog = load_raw_catalog(catalog_path)
    idx = ControlIndex(catalog, engine.tokenizer)
    old = json.loads(Path(path).read_text(encoding="utf-8"))["links"] if update and Path(path).exists() else {}
    links = {}
    for c in engine.search_cards:
        sid = linker.for_card(c["id"]).get("scenario_id")
        if not sid:
            continue
        for text in pool(engine, c):
            k = key(sid, text)
            if k in links:
                continue
            cid, score = idx.best(sid, engine.actions.get(text, text) + " " + text)
            links[k] = dict(control_id=cid if score >= LINK else None, score=score,
                            candidate=cid, confirmed=old.get(k, {}).get("confirmed"), note=old.get(k, {}).get("note", ""))
    doc = {"_note": "카드 대책 문장 → 시나리오 기준 조치 연결. 키는 '시나리오 ID|대책 원문'. control_id는 자동 후보(검토 전 초안)이며 "
                    f"점수 {LINK} 미만은 연결하지 않는다. 검토 팀원이 confirmed에 조치 ID 또는 'none'을 적으면 그 값을 쓴다.",
           "catalog_policy": catalog["policy_version"], "link_min": LINK, "links": links}
    Path(path).write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return doc


class ControlMapper:
    """(시나리오 ID, 대책 원문) → 기준 조치 연결. 위험도 계산은 하지 않는다."""

    def __init__(self, map_path=MAP, catalog_path=CATALOG, count_auto=False):
        self.count_auto = count_auto
        doc = json.loads(Path(map_path).read_text(encoding="utf-8"))
        self.links = doc["links"]
        self.controls = {(s["id"], c["id"]): c for s in load_raw_catalog(catalog_path)["scenarios"] for c in s["controls"]}

    def link(self, scenario_id, original):
        e = self.links.get(key(scenario_id, original))
        if not e:
            return dict(control_id=None, status="unmapped", message="연결표에 없는 대책 · 위험도 계산 제외")
        confirmed = e.get("confirmed")
        if confirmed == "none":
            return dict(control_id=None, status="none", message="검토 결과 맞는 기준 조치 없음 · 위험도 계산 제외")
        cid = confirmed or e.get("control_id")
        if not cid or (scenario_id, cid) not in self.controls:
            return dict(control_id=None, status="weak", score=e.get("score"),
                        message="비슷한 기준 조치 없음 · 위험도 계산 제외")
        c = self.controls[(scenario_id, cid)]
        view = dict(candidate_id=cid, critical=c["critical"], control_text=c["current_text"], score=e.get("score"))
        if confirmed:
            return dict(view, control_id=cid, status="confirmed", message="검토 완료 · 위험도 계산 반영")
        if self.count_auto:
            return dict(view, control_id=cid, status="auto", message="자동 연결 · 검토 전 · 시험용으로 위험도 계산 반영")
        return dict(view, control_id=None, status="auto_pending", message="자동 연결 · 검토 전 · 위험도 계산 제외")

    def info(self):
        return dict(count_auto=self.count_auto, links=len(self.links), linked=sum(1 for v in self.links.values() if v.get("control_id")),
                    confirmed=sum(1 for v in self.links.values() if v.get("confirmed")))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--update", action="store_true")
    ap.add_argument("--data", default=str(HERE.parents[1] / "docs" / "chroma"))
    a = ap.parse_args()
    from .engine import Engine
    from .scenario_map import ScenarioLinker
    eng = Engine(a.data, mode="keyword", log=lambda m: None)
    doc = build(eng, ScenarioLinker(), update=a.update)
    n = len(doc["links"])
    linked = sum(1 for v in doc["links"].values() if v["control_id"])
    print(f"저장: {MAP} (대책 {n}개, 기준 조치 연결 {linked}개, 미연결 {n - linked}개)")


if __name__ == "__main__":
    main()
