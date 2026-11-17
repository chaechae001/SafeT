"""추천형 비교 보고서(내부)를 만든다. 모델 호출 없음.
python src/report_hitl.py → runs/hitl_recommend/hitl_comparison_internal.md
"""
from __future__ import annotations

import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from s04_pipeline import ROOT, now_kst  # noqa: E402

OUT = ROOT / "runs" / "hitl_recommend"
LABEL = {"R_bm25": "검색만(BM25)", "R_index": "검색만(기기마스터 v1 인덱스)", "R_index_v2": "검색만(인덱스 v2, 엄격)",
         "A_llm": "LLM 단독", "B_rag": "RAG+LLM(LLM이 고른 것만)", "B_rag_fill": "RAG+LLM(+나머지 검색 후보)",
         "E_exaone": "RAG(인덱스 v2)+EXAONE API", "E35_awq": "RAG(인덱스 v2)+EXAONE 3.5 7.8B AWQ",
         "E35_awq_enum": "RAG(인덱스 v2)+EXAONE 3.5 7.8B AWQ(enum 강제)"}
STATS = {"E_exaone": "exaone_stats.json", "E35_awq": "exaone35_awq_stats.json", "E35_awq_enum": "exaone35_awq_enum_stats.json"}


def model_compare(g: dict, st: dict, cv: dict) -> list[str]:
    """요청 지표 비교: 검색만 / Qwen2.5-VL-3B(Cloud) / EXAONE API(외부)."""
    p = OUT / "exaone_stats.json"
    if not p.exists():
        return []
    ex = json.loads(p.read_text(encoding="utf-8"))
    exs = {m: json.loads((OUT / f).read_text(encoding="utf-8")) for m, f in STATS.items() if (OUT / f).exists()}
    subs = list(g["subsets"].items())[:2]
    rows = [("R_bm25", "검색만(BM25)", "없음"), ("R_index", "검색만(기기마스터 v1)", "없음"),
            ("R_index_v2", "검색만(인덱스 v2, 엄격)", "없음"),
            ("A_llm", "Qwen2.5-VL-3B 단독", "Elice Cloud"), ("B_rag", "Qwen2.5-VL-3B RAG(기기마스터 v1 후보)", "Elice Cloud"),
            ("E35_awq", "EXAONE 3.5 7.8B AWQ RAG(인덱스 v2 후보)", "Elice Cloud"),
            ("E35_awq_enum", "EXAONE 3.5 7.8B AWQ RAG(enum 강제)", "Elice Cloud"),
            ("E_exaone", "K-EXAONE 2.5 RAG(인덱스 v2 후보)", "EXAONE API(외부)")]
    rows = [r for r in rows if r[0] not in STATS or r[0] in exs]
    L = ["## 모델 비교 — 요청 지표 (내부 비교)", "",
         "| 방법 | 실행 위치 | 누출 제외 R@1 | R@3 | P@3 | 누출 포함 R@1 | R@3 | P@3 | 계약 v2 통과 | 후보 밖·목록 밖 코드 | 출처 오류 | 호출당 응답 시간(초) |",
         "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for m, name, loc in rows:
        sc = []
        for _, sub in subs:
            r = sub.get(m)
            sc += [f"{r['R@1']:.2f}", f"{r['R@3']:.2f}", f"{r['P@3']:.2f}"] if r else ["-"] * 3
        if m in exs:
            e = exs[m]
            schema = f"{e['schema_valid']}/{e['responses']}"
            outside, srcerr, sec = e["outside_pool_codes"], e["invalid_source_ids"], e["seconds_mean"]
        else:
            c = cv["methods"].get(m)
            schema = f"{c['valid']}/{c['responses']}" if c else "-"
            ls = st.get("llm_stats", {}).get(m)
            outside = sum(s.get("invalid_code", 0) + s.get("outside_pool", 0) for s in ls) if ls else 0
            srcerr = "해당 없음"
            sec = round(statistics.mean(s["seconds"] for s in ls), 2) if ls else "-"
        L.append(f"| {name} | {loc} | " + " | ".join(sc) + f" | {schema} | {outside} | {srcerr} | {sec} |")
    L += ["",
          f"- K-EXAONE 2.5: 호출 {ex['calls']}회(근거 있는 기기만), 파싱 성공 {ex['parse_ok']}, 재시도 {ex['retries']}, 출처 오류로 버린 후보 {ex['dropped_no_valid_source']}, "
          f"평균 출력 토큰 {ex['completion_tokens_mean']}(추론 {ex['reasoning_tokens_mean']}), 최대 응답 {ex['seconds_max']}초. 근거 없는 기기 17개는 호출하지 않고 no_source_found.",
          "- 응답 시간 조건이 다르다. Qwen은 Cloud GPU 생성 시간(모델 로딩·네트워크 제외), EXAONE은 네트워크·대기·추론을 포함한 요청 왕복 시간이다.",
          "- 후보 풀이 다르다. Qwen RAG는 기기마스터 v1 후보(누출 경로 있음), EXAONE은 인덱스 v2 엄격 후보(사례 제외)다. 같은 후보로 비교한 것이 아니다.",
          "- '후보 밖·목록 밖 코드': Qwen 단독은 14개 코드 목록 밖, RAG 방법은 주어진 후보 밖 코드 수. 검색만 방법은 구조상 0이다.",
          "- 위험도 계산(3×3)은 사용자 결정(2026-11-16, 노션 H1 척도 + 중대성 3이면 빨강)이며 전문가 채택 전(proposed)이다. LLM 출력과 무관하게 사용자 선택값으로 규칙 계산만 한다(`config/risk_rule_3x3_notion_v1.json`, `runs/hitl_recommend/risk_rule_check.json`).", ""]
    return L


def four_way(g: dict, st: dict) -> list[str]:
    """요청 열 순서: 검색만 / Qwen2.5-VL-3B / EXAONE 3.5 7.8B AWQ / K-EXAONE 2.5 API. 기준선 없이 수치만."""
    if not all((OUT / f).exists() for f in STATS.values()):
        return []
    exs = {m: json.loads((OUT / f).read_text(encoding="utf-8")) for m, f in STATS.items()}
    cols = [("R_index_v2", "검색만(인덱스 v2)"), ("B_rag", "Qwen2.5-VL-3B(RAG, v1 후보)"),
            ("E35_awq", "EXAONE 3.5 7.8B AWQ"), ("E35_awq_enum", "EXAONE 3.5 7.8B AWQ(enum 강제)"), ("E_exaone", "K-EXAONE 2.5 API")]
    L = ["## 4열 비교(+enum 강제 열) — 검색만 / Qwen2.5-VL-3B / EXAONE 3.5 7.8B AWQ / K-EXAONE 2.5 API (내부 비교, 판정 기준선 없음)", "",
         "| 지표 | " + " | ".join(n for _, n in cols) + " |", "|---|" + "---|" * len(cols)]
    for sname, sub in list(g["subsets"].items())[:2]:
        for k in ("R@1", "P@1", "R@3", "P@3", "R@5", "P@5"):
            L.append(f"| {sname} {k} | " + " | ".join(f"{sub[m][k]:.2f}" if sub.get(m) else "-" for m, _ in cols) + " |")
    ls = st.get("llm_stats", {}).get("B_rag") or []
    def q(m, key):
        if m == "R_index_v2":
            return "해당 없음"
        if m == "B_rag":
            return {"parse": f"{sum(s['parse_ok'] for s in ls)}/{len(ls)}",
                    "retry": sum(len(s.get('attempts', [])) - 1 if s.get('attempts') else (s['accepted_attempt'] or 1) - 1 for s in ls),
                    "src": "해당 없음(출처는 서버가 붙임)", "out": sum(s.get("invalid_code", 0) + s.get("outside_pool", 0) for s in ls),
                    "sec": round(statistics.mean(s["seconds"] for s in ls), 2) if ls else "-"}[key]
        e = exs[m]
        return {"parse": f"{e['parse_ok']}/{e['calls']}", "retry": e["retries"],
                "src": f"출처 오류 {e['invalid_source_ids']}건(남은 후보 {e['candidates']})",
                "out": f"{e['outside_pool_codes']}(중복 {e['dup_codes']})", "sec": e["seconds_mean"]}[key]
    for key, name in (("parse", "JSON 파싱 성공(호출 기준)"), ("retry", "재시도 수"), ("out", "후보 밖 코드 수"),
                      ("src", "출처 ID 유효성"), ("sec", "질의당 처리 시간 평균(초)")):
        L.append(f"| {name} | " + " | ".join(str(q(m, key)) for m, _ in cols) + " |")
    L += ["",
          "- 정답 질의는 기기 질의 7개(누출 제외 4개)뿐이다. 질의 1개가 R@K를 0.14~0.25 움직이므로 열 사이 차이는 우연일 수 있다. 판정 기준선은 정하지 않았다.",
          "- 처리 시간 조건이 다르다. Qwen·EXAONE 3.5는 Cloud GPU 생성 시간(로딩 제외), K-EXAONE는 네트워크·대기 포함 왕복 시간이다.",
          "- EXAONE 3.5와 K-EXAONE는 같은 프롬프트 파일(api/prompts_exaone_hitl_v1.json)과 같은 후처리를 썼다. Qwen RAG는 기기마스터 v1 후보라 후보 풀이 다르다.",
          "- EXAONE 3.5는 vLLM guided JSON으로 구조만 강제했다. 코드·출처 ID 값은 강제하지 않아 후보 밖 코드가 측정된다.",
          "- EXAONE 3.5(enum 강제)는 호출마다 후보 코드 const와 그 후보의 출처 ID enum을 anyOf로 묶고 항목 수를 후보 수 이하로 제한했다. xgrammar가 uniqueItems를 지원하지 않아 뺐다. 같은 코드 반복(항목 간 중복)은 스키마로 막지 못한다.", ""]
    return L


def main():
    ev = json.loads((OUT / "eval_hitl_goldset_v2.json").read_text(encoding="utf-8"))
    g = ev["goldset_eval"]
    st = json.loads((OUT / "run_stats.json").read_text(encoding="utf-8"))
    cv = json.loads((OUT / "contract_v2" / "contract_v2_check.json").read_text(encoding="utf-8"))
    ck = json.loads((OUT / "check_hitl.json").read_text(encoding="utf-8"))
    methods = list(next(iter(g["subsets"].values())).keys())
    methods.remove("queries")
    L = [f"# 추천형(HITL) 위험요인 후보 비교 — 내부 비교 (생성 {now_kst()})", "",
         "- 판정·점수는 내부 비교다. 성능 향상이나 현장 안전 성능으로 읽지 않는다.",
         f"- 모델: {ev['model_version'] or '없음(검색만)'}. 정답셋: `{g['goldset']}` (RAG 세션, 전문가 검수 전).",
         f"- 정답셋 질의 {g['queries_total']}개 중 기기 질의 {g['equipment_queries']}개만 평가했다. "
         f"작업 질의 {len(g['not_evaluated'])}개({', '.join(x['gold_id'] for x in g['not_evaluated'])})는 입력 형식이 달라 미평가.",
         "- 정의: 질의마다 Recall@K = 맞힌 정답 코드 수/정답 코드 수, Precision@K = 맞힌 수/K(후보가 K개보다 적어도 분모 K). 질의 평균.",
         "- 정답은 평가자가 실제로 적은 위험만 담는다. 타당하지만 기록되지 않은 후보도 오답으로 계산되므로 Precision은 하한값이다.",
         "- '누출 경로' 표시: 기기마스터 v1을 쓰는 방법(R_index, B_rag, B_rag_fill)은 G-R01·R02·R04의 같은 사례가 기기마스터 근거로 쓰였다.", ""]
    for name, sub in g["subsets"].items():
        L += [f"## {name} — 질의 {len(sub['queries'])}개 ({', '.join(sub['queries'])})", "",
              "| 방법 | R@1 | P@1 | R@3 | P@3 | R@5 | P@5 | 누출 경로 질의 |", "|---|---|---|---|---|---|---|---|"]
        for m in methods:
            r = sub[m]
            L.append(f"| {LABEL.get(m, m)} | {r['R@1']:.2f} | {r['P@1']:.2f} | {r['R@3']:.2f} | {r['P@3']:.2f} | "
                     f"{r['R@5']:.2f} | {r['P@5']:.2f} | {', '.join(r['leak_path_queries']) or '-'} |")
        L.append("")
    L += ["## 질의별 상위 5개 후보", "", "| 질의 | 기기 | 정답 | 누출 | 인덱스 v2 근거 없음 | " + " | ".join(LABEL.get(m, m) for m in methods) + " |",
          "|---|---|---|---|---|" + "---|" * len(methods)]
    for q in g["per_query"]:
        cells = []
        for m in methods:
            hit = set(q["hits@5"][m])
            cells.append(", ".join(f"**{c}**" if c in hit else c for c in q["top5"][m]) or "(없음)")
        L.append(f"| {q['gold_id']} | {q['equipment_id']} | {', '.join(q['gold'])} | {q['leakage_risk'][:2]} | "
                 f"{'근거 없음' if q['index_v2_no_evidence'] else '-'} | " + " | ".join(cells) + " |")
    L += ["", "굵은 글씨 = 정답 코드.", ""]
    if st.get("llm_stats", {}).get("A_llm"):
        L += ["## LLM 호출 상태(Cloud 응답 재생)", "", "| 방법 | 호출 | 파싱 성공(채택 시도) | 재시도 | 평균 후보 수 | 코드 오류·중복·후보 밖 | 평균 생성 시간(초) |",
              "|---|---|---|---|---|---|---|"]
        for m in ("A_llm", "B_rag"):
            x = st["llm_stats"][m]
            bad = sum(s.get("invalid_code", 0) + s.get("outside_pool", 0) + s.get("dup_code", 0) + s.get("empty", 0) for s in x)
            L.append(f"| {LABEL[m]} | {len(x)} | {sum(s['parse_ok'] for s in x)} | {sum((s['accepted_attempt'] or 9) > 1 for s in x)} | "
                     f"{statistics.mean(s['n'] for s in x):.2f} | {bad} | {statistics.mean(s['seconds'] for s in x):.1f} |")
        L += ["", f"- C1(대책 선택) 규칙 위반 → C2 대체 단위: {len(st['c1_invalid_units'])}개.", ""]
    L += ["## 계약 v2 검증(`hazard_candidates.v2.response.schema.json`)", "",
          "| 방법 | 통과 | 후보(변환 전→후) | 서버가 출처 붙임 | 출처 없어 버림 | no_source_found 기기 |", "|---|---|---|---|---|---|"]
    for m, s in cv["methods"].items():
        L.append(f"| {LABEL.get(m, m)} | {s['valid']}/{s['responses']} | {s['candidates_in']}→{s['candidates_out']} | {s['server_attached']} | "
                 f"{s['dropped_no_source']} | {s['no_source_found_groups']} |")
    # 계약 v2 적용 후(출처 없는 후보 제거) 같은 정답셋 점수
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from eval_hitl import GOLDSET, at_k
    gold = [json.loads(x) for x in GOLDSET.read_text(encoding="utf-8").splitlines() if x.strip()]
    eqq = [q for q in gold if q["query"]["type"] == "equipment"]
    subs = {"누출위험_제외": [q for q in eqq if q["leakage_risk"].startswith("낮음")], "누출위험_포함": eqq}
    L += ["", "### 계약 v2 적용 후 점수(출처 없는 후보를 버린 뒤, 같은 정답셋)", "",
          "| 방법 | 누출 제외 R@3 | 누출 제외 P@3 | 누출 포함 R@3 | 누출 포함 P@3 |", "|---|---|---|---|---|"]
    for m in cv["methods"]:
        conv = json.loads((OUT / "contract_v2" / f"v2_{m}.json").read_text(encoding="utf-8"))
        rk = {gr["equipment_id"]: [c["accident_type"]["code"] for c in gr["candidates"]]
              for x in conv if x["request_id"].startswith("hitl-eq-") for gr in x["groups"]}
        cells = []
        for qs in subs.values():
            res = [at_k(rk.get(q["query"]["equipment_id"], []), set(q["gold_hazard_codes"]), 3) for q in qs]
            cells += [f"{sum(r[0] for r in res) / len(res):.2f}", f"{sum(r[1] for r in res) / len(res):.2f}"]
        L.append(f"| {LABEL.get(m, m)} | " + " | ".join(cells) + " |")
    rka = json.loads((OUT / "ranked_codes.json").read_text(encoding="utf-8"))["ranked"]
    if "A_llm" in rka:
        from collections import Counter
        top1 = Counter(v[0] for v in rka["A_llm"].values() if v).most_common(3)
        seq = Counter(tuple(v[:6]) for v in rka["A_llm"].values()).most_common(1)[0]
        L += ["", "### LLM 단독 출력 특성", "",
              f"- 1순위 코드 분포(기기 42개): {top1}. 같은 6개 순서 `{', '.join(seq[0])}`가 {seq[1]}개 기기에서 나왔다.",
              "- 프롬프트의 코드 목록 순서(slip, cut, burn, fire, …)를 따라 쓰는 경향으로 보인다(가설). 기기와 무관한 후보가 많다.", ""]
    L += ["", f"- 음성 시험(판단 필드·빈 출처 거부): {cv['negative_tests']}",
          f"- 로컬 초안 스키마(contract_hitl) 점검: {'통과' if ck['all_ok'] else '실패'}, 음성 시험 {ck['negative_tests']}", ""]
    L += model_compare(g, st, cv)
    L += four_way(g, st)
    (OUT / "hitl_comparison_internal.md").write_text("\n".join(L), encoding="utf-8")
    print("\n".join(L))


if __name__ == "__main__":
    main()
