"""추천 후보 사람 판정 시트(블라인드)를 만들고, 판정이 끝난 시트를 방법별로 집계한다. 모델 호출 없음.

대상: 근거 있는 기기 25개(api/prompts_exaone_hitl_v1.json 의 calls)
방법 4개: R_index_v2(검색만), E35_awq(EXAONE 3.5 AWQ), E_exaone(K-EXAONE API), B_rag(Qwen RAG)
- 같은 기기의 후보 코드는 방법 간에 합쳐 한 행으로 만든다. 어느 방법이 냈는지는 시트에 없다(대응표 파일에만 있음).
- 설명문은 LLM이 쓴 것만 넣는다(E35_awq·E_exaone·B_rag). R_index_v2 설명문은 서버 고정 문구라 넣으면
  방법이 드러나므로 제외한다. 설명문 순서는 행마다 고정 시드로 섞어 A·B·C로 익명화한다.
- 근거 문장은 공개 자료(점검표·안내서·실태조사 보고서)만 쓴다. CASE-*(사례)·회사 원본·사진·정답셋 원문은 넣지 않는다.
- 판정 칸은 비워 둔다. AI가 판정을 채우지 않는다.

사용:
  uv run --with openpyxl python src/judge_hitl.py build              → 시트·대응표 생성
  uv run --with openpyxl python src/judge_hitl.py aggregate <xlsx>   → 방법별 집계(JSON·MD)
  uv run --with openpyxl python src/judge_hitl.py selftest           → 합성 판정값으로 집계 자체 시험
"""
from __future__ import annotations

import csv
import hashlib
import json
import random
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RUNS = ROOT / "runs" / "hitl_recommend"
OUT = RUNS / "judgement"
KB = ROOT.parent / "261115_RAG_지식베이스_DR"
PROMPTS = ROOT / "api" / "prompts_exaone_hitl_v1.json"
SHEET = OUT / "hitl_판정시트_v1.xlsx"
MAPPING = OUT / "hitl_판정_대응표_v1.json"
SEED = 20261116
METHODS = ("R_index_v2", "E35_awq", "E_exaone", "B_rag")
METHOD_NAME = {"R_index_v2": "검색만(인덱스 v2)", "E35_awq": "EXAONE 3.5 7.8B AWQ", "E_exaone": "K-EXAONE 2.5 API",
               "B_rag": "Qwen2.5-VL-3B RAG"}
LLM_METHODS = ("E35_awq", "E_exaone", "B_rag")
VERDICTS = ("정답", "타당하나 미기록", "부적절")
RAT_VERDICTS = ("적절", "부분 적절", "부적절")
REVIEWER = ("작성자(비전문가) 검토", "전문가 검수")
LABELS = ("A", "B", "C")
SHEET_NAME = "판정"
COLS = ["판정ID", "기기ID", "기기명", "위험코드", "위험명칭", "위험 설명(근거 행)", "근거 출처 ID", "근거 문장(공개 자료)",
        "후보 판정", "설명문 A", "설명문 A 적절성", "설명문 B", "설명문 B 적절성", "설명문 C", "설명문 C 적절성",
        "판정자 구분", "판정자", "판정일", "메모"]


# ---------------------------------------------------------------- 근거 문장(공개 자료만)
def _jsonl(p: Path) -> list[dict]:
    return [json.loads(l) for l in p.read_text(encoding="utf-8").splitlines() if l.strip()]


def _clip(t: str, n: int = 160) -> str:
    t = re.sub(r"\s+", " ", t or "").strip()
    return t if len(t) <= n else t[: n - 1] + "…"


class Evidence:
    PUBLIC_LINK_TYPES = {"checklist", "d8_table", "d5_visual"}

    def __init__(self):
        self.link = {}      # (eid, code, sid) -> hazard_text
        self.link_any = {}  # sid -> hazard_text
        for l in _jsonl(KB / "261116_RAG_기기위험요인링크_v2_DR.jsonl"):
            if l["source_type"] not in self.PUBLIC_LINK_TYPES or l["source_id"].startswith("CASE-"):
                continue
            self.link[(l["equipment_id"], l["hazard_code"], l["source_id"])] = l["hazard_text"]
            self.link_any.setdefault(l["source_id"], l["hazard_text"])
        self.chunk = {c["chunk_id"]: c["text"] for c in _jsonl(KB / "261115_RAG_청크_v1_DR.jsonl")}
        self.row = {r["row_id"]: r.get("source_text") for r in _jsonl(KB / "261115_RAG_구조화표_v1_DR.jsonl")
                    if r.get("source_type") != "case"}

    def text(self, eid: str, code: str, sid: str) -> str | None:
        if sid.startswith("CASE-"):
            return None
        t = self.link.get((eid, code, sid)) or self.link_any.get(sid) or self.row.get(sid) or self.chunk.get(sid)
        return _clip(t) if t else None


# ---------------------------------------------------------------- 시트 생성
def collect() -> tuple[list[str], dict, dict]:
    calls = json.loads(PROMPTS.read_text(encoding="utf-8"))["calls"]
    eids = [c["equipment_id"] for c in calls]
    cands = defaultdict(dict)   # (eid, code) -> method -> candidate
    names = {}
    for m in METHODS:
        for resp in json.loads((RUNS / "contract_v2" / f"v2_{m}.json").read_text(encoding="utf-8")):
            for g in resp["groups"]:
                if g["equipment_id"] not in eids:
                    continue
                names[g["equipment_id"]] = g["display_name"]
                for rank, c in enumerate(g["candidates"], 1):
                    cands[(g["equipment_id"], c["accident_type"]["code"])][m] = dict(c, rank=rank)
    return eids, cands, names


def build_rows():
    eids, cands, names = collect()
    ev = Evidence()
    rng = random.Random(SEED)
    rows, mapping = [], []
    keys = sorted(cands, key=lambda k: (eids.index(k[0]), k[1]))   # 기기 순서 → 코드 알파벳(방법 순위가 드러나지 않게)
    for i, (eid, code) in enumerate(keys, 1):
        by_m = cands[(eid, code)]
        jid = f"J{i:03d}"
        any_c = next(iter(by_m.values()))
        sids = []
        for m in METHODS:
            for s in by_m.get(m, {}).get("source_refs", []):
                if s["source_id"] not in sids and not s["source_id"].startswith("CASE-"):
                    sids.append(s["source_id"])
        # 가독성 규칙: 근거 문장이 같으면 한 줄로 합치고 출처 ID를 모은다("[ID1, ID2] 문장").
        merged: dict[str, list[str]] = {}
        for s in sids:
            t = ev.text(eid, code, s) or "문장 미확인"
            merged.setdefault(t, []).append(s)
        texts = [f"[{', '.join(ids)}] {t}" for t, ids in merged.items()]
        hz = next((by_m[m]["hazard"] for m in ("R_index_v2", "E35_awq", "E_exaone", "B_rag") if m in by_m), "")
        rats = [(m, by_m[m]["rationale"]) for m in LLM_METHODS if m in by_m and (by_m[m].get("rationale") or "").strip()]
        # 가독성 규칙: 같은 설명문(공백 정리 후 동일)은 한 칸으로 합친다. 그 칸의 판정은 해당 방법 모두에 집계한다.
        uniq: dict[str, list[str]] = {}
        for m, r in rats:
            uniq.setdefault(re.sub(r"\s+", " ", r).strip(), []).append(m)
        rats = [(ms, r) for r, ms in uniq.items()]
        rng.shuffle(rats)
        row = {"판정ID": jid, "기기ID": eid, "기기명": names[eid], "위험코드": code, "위험명칭": any_c["accident_type"]["label"],
               "위험 설명(근거 행)": hz, "근거 출처 ID": ", ".join(sids), "근거 문장(공개 자료)": "\n".join(texts)}
        rmap = {}
        for lab, (m, r) in zip(LABELS, rats):
            row[f"설명문 {lab}"] = r
            rmap[lab] = m if len(m) > 1 else m[0]
        rows.append(row)
        mapping.append({"판정ID": jid, "equipment_id": eid, "hazard_code": code,
                        "proposed_by": {m: by_m[m]["rank"] for m in METHODS if m in by_m},
                        "rationale_labels": rmap})
    return eids, rows, mapping


def write_sheet(rows: list[dict], path: Path, note_extra: str = ""):
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.worksheet.datavalidation import DataValidation
    wb = Workbook()
    ws = wb.active
    ws.title = SHEET_NAME
    ws.append(COLS)
    for r in rows:
        ws.append([r.get(c) for c in COLS])
    n = len(rows) + 1
    widths = {"판정ID": 8, "기기ID": 18, "기기명": 12, "위험코드": 14, "위험명칭": 14, "위험 설명(근거 행)": 30,
              "근거 출처 ID": 22, "근거 문장(공개 자료)": 60, "후보 판정": 14, "설명문 A": 40, "설명문 B": 40, "설명문 C": 40,
              "설명문 A 적절성": 12, "설명문 B 적절성": 12, "설명문 C 적절성": 12, "판정자 구분": 20, "판정자": 10, "판정일": 12, "메모": 30}
    from openpyxl.utils import get_column_letter
    col = {c: get_column_letter(i + 1) for i, c in enumerate(COLS)}
    for c, w in widths.items():
        ws.column_dimensions[col[c]].width = w
    fill = PatternFill("solid", fgColor="FFF2CC")
    for c in COLS:
        ws[f"{col[c]}1"].font = Font(bold=True)
        if c in ("후보 판정", "설명문 A 적절성", "설명문 B 적절성", "설명문 C 적절성", "판정자 구분", "판정자", "판정일", "메모"):
            ws[f"{col[c]}1"].fill = fill
    for row in ws.iter_rows(min_row=2, max_row=n):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = "C2"

    def dv(values, cols):
        d = DataValidation(type="list", formula1='"' + ",".join(values) + '"', allow_blank=True,
                           showErrorMessage=True, errorTitle="입력 값", error="목록에서 고르세요.")
        ws.add_data_validation(d)
        for c in cols:
            d.add(f"{col[c]}2:{col[c]}{n}")
    dv(VERDICTS, ["후보 판정"])
    dv(RAT_VERDICTS, ["설명문 A 적절성", "설명문 B 적절성", "설명문 C 적절성"])
    dv(REVIEWER, ["판정자 구분"])

    g = wb.create_sheet("안내")
    for line in [
        "추천 후보 사람 판정 시트 v1 (블라인드)",
        "",
        "1. 한 행은 '기기 × 위험코드' 후보 하나다. 여러 추천 방법이 낸 후보를 합쳤고, 어느 방법이 냈는지는 숨겼다.",
        "2. 후보 판정: 정답 = 이 기기에서 이 위험요인을 평가 항목으로 올려야 한다. 타당하나 미기록 = 그럴듯하지만 근거 자료·정답셋에 없다. 부적절 = 이 기기와 맞지 않는다.",
        "3. 설명문 A·B·C: 서로 다른 방법이 쓴 설명이다(순서는 행마다 무작위). 빈칸이면 그 수만큼만 설명이 있다. 적절성은 근거 문장과 맞는지, 위험 정도(높다·낮다)를 단정하지 않는지로 본다.",
        "4. 판정자 구분: 작성자(비전문가) 검토와 전문가 검수를 반드시 구분해 적는다. 같은 행을 두 사람이 보면 행을 복사해 아래에 붙이고 판정자 구분을 다르게 적는다.",
        "5. 근거 문장은 공개 자료(점검표, 서비스업 위험성평가 안내서, 프랜차이즈 실태조사 보고서) 발췌다. 160자에서 잘랐다. 같은 문장은 한 줄로 합치고 출처 ID를 모았다. 같은 설명문도 한 칸으로 합쳤다.",
        "6. 위험도·등급·신호는 판정하지 않는다. 3×3 위험도는 임시 가정(팀·전문가 확정 전)이며 이 시트 범위 밖이다.",
        "7. 판정이 끝나면 src/judge_hitl.py aggregate <이 파일> 로 방법별 집계를 낸다.",
        "",
        f"생성 시드 {SEED}. 대상 기기 25개(근거 있는 기기). 근거 없는 기기 17개는 후보가 없어 제외.",
    ] + ([note_extra] if note_extra else []):
        g.append([line])
    g.column_dimensions["A"].width = 140
    wb.save(path)


def cmd_build():
    OUT.mkdir(parents=True, exist_ok=True)
    eids, rows, mapping = build_rows()
    write_sheet(rows, SHEET)
    MAPPING.write_text(json.dumps({"seed": SEED, "methods": METHOD_NAME, "equipment": eids,
                                   "note": "판정 시트와 분리 보관. 판정이 끝나기 전에는 판정자에게 보여주지 않는다.",
                                   "rows": mapping}, ensure_ascii=False, indent=1), encoding="utf-8")
    with (OUT / "hitl_판정_대응표_v1.csv").open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(["판정ID", "기기ID", "위험코드"] + [f"{m}_순위" for m in METHODS] + ["설명문 A", "설명문 B", "설명문 C"])
        for m in mapping:
            w.writerow([m["판정ID"], m["equipment_id"], m["hazard_code"]] + [m["proposed_by"].get(x, "") for x in METHODS]
                       + ["+".join(x) if isinstance(x, list) else x for x in (m["rationale_labels"].get(l, "") for l in LABELS)])
    st = {"rows": len(rows), "equipment": len(eids), "per_method_candidates": {m: sum(m in x["proposed_by"] for x in mapping) for m in METHODS},
          "rationales": sum(len(x["rationale_labels"]) for x in mapping),
          "evidence_missing_text": sum(r["근거 문장(공개 자료)"].count("문장 미확인") for r in rows),
          "sheet_sha256": hashlib.sha256(SHEET.read_bytes()).hexdigest()}
    print(json.dumps(st, ensure_ascii=False))
    return st


# ---------------------------------------------------------------- 집계
def read_sheet(path: Path) -> list[dict]:
    from openpyxl import load_workbook
    ws = load_workbook(path, read_only=True)[SHEET_NAME]
    it = ws.iter_rows(values_only=True)
    head = list(next(it))
    return [dict(zip(head, r)) for r in it if r and r[0]]


def aggregate(rows: list[dict], mapping: dict) -> dict:
    mp = {m["판정ID"]: m for m in mapping["rows"]}
    n_eq = len(mapping["equipment"])
    res = {}
    for reviewer in REVIEWER + ("구분 없음",):
        rs = [r for r in rows if (r.get("판정자 구분") or "구분 없음") == reviewer]
        if not rs:
            continue
        out = {}
        for m in METHODS:
            v = Counter()
            rv = Counter()
            for r in rs:
                info = mp[r["판정ID"]]
                if m in info["proposed_by"]:
                    v[r.get("후보 판정") or "미판정"] += 1
                for lab, mm in info["rationale_labels"].items():
                    if m == mm or (isinstance(mm, list) and m in mm):
                        rv[r.get(f"설명문 {lab} 적절성") or "미판정"] += 1
            judged = sum(v[x] for x in VERDICTS)
            rjudged = sum(rv[x] for x in RAT_VERDICTS)
            out[m] = {"name": METHOD_NAME[m], "candidates": sum(v.values()), "candidates_per_query": round(sum(v.values()) / n_eq, 2),
                      "judged": judged, "unjudged": v["미판정"],
                      **{f"ratio_{x}": (round(v[x] / judged, 3) if judged else None) for x in VERDICTS},
                      "counts": {x: v[x] for x in VERDICTS},
                      "rationale_judged": rjudged,
                      **{f"rationale_ratio_{x}": (round(rv[x] / rjudged, 3) if rjudged else None) for x in RAT_VERDICTS}}
        res[reviewer] = out
    return res


def to_md(res: dict, title: str) -> str:
    L = [f"# {title}", "", "내부 집계. 판정 기준선은 정하지 않았다. 작성자(비전문가) 검토와 전문가 검수는 따로 집계한다.", ""]
    for reviewer, out in res.items():
        L += [f"## {reviewer}", "", "| 방법 | 후보 수 | 질의당 후보 | 판정 수 | 정답 | 타당하나 미기록 | 부적절 | 설명문 판정 수 | 설명 적절 | 부분 적절 | 부적절 |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
        f = lambda x: "-" if x is None else f"{x:.2f}"
        for m, o in out.items():
            L.append(f"| {o['name']} | {o['candidates']} | {o['candidates_per_query']} | {o['judged']} | {f(o['ratio_정답'])} | "
                     f"{f(o['ratio_타당하나 미기록'])} | {f(o['ratio_부적절'])} | {o['rationale_judged']} | {f(o['rationale_ratio_적절'])} | "
                     f"{f(o['rationale_ratio_부분 적절'])} | {f(o['rationale_ratio_부적절'])} |")
        L.append("")
    L.append("- 비율의 분모는 그 방법 후보 중 판정된 수다. 질의당 후보는 대상 기기 25개 기준이다. 검색만(인덱스 v2)은 설명문이 없어 설명 칸이 비어 있다.")
    return "\n".join(L) + "\n"


def cmd_aggregate(path: Path, tag: str = "") -> dict:
    mapping = json.loads(MAPPING.read_text(encoding="utf-8"))
    res = aggregate(read_sheet(path), mapping)
    stem = f"hitl_판정집계{tag}"
    (OUT / f"{stem}.json").write_text(json.dumps({"source": path.name, "result": res}, ensure_ascii=False, indent=1), encoding="utf-8")
    md = to_md(res, f"판정 집계 — {path.name}")
    if "합성" in tag:
        md = md.replace("\n\n내부 집계.", "\n\n**※ 합성 판정값(무작위)으로 만든 자체 시험 결과다. 실제 판정이나 성능이 아니다.**\n\n내부 집계.", 1)
    (OUT / f"{stem}.md").write_text(md, encoding="utf-8")
    print(json.dumps({k: {m: (o["judged"], o["ratio_정답"]) for m, o in v.items()} for k, v in res.items()}, ensure_ascii=False))
    return res


# ---------------------------------------------------------------- 자체 시험(합성 판정값)
def cmd_selftest():
    if not SHEET.exists():
        cmd_build()
    mapping = json.loads(MAPPING.read_text(encoding="utf-8"))
    rows = read_sheet(SHEET)
    assert all(not r.get("후보 판정") and not r.get("판정자 구분") for r in rows), "원본 시트 판정 칸이 비어 있지 않다"
    rng = random.Random(7)
    syn = []
    for r in rows:
        x = dict(r)
        x["후보 판정"] = rng.choice(VERDICTS + (None,))
        for lab in LABELS:
            if x.get(f"설명문 {lab}"):
                x[f"설명문 {lab} 적절성"] = rng.choice(RAT_VERDICTS)
        x["판정자 구분"] = REVIEWER[0]
        x["메모"] = "합성 판정값(자체 시험용, 실제 판정 아님)"
        syn.append(x)
    syn += [dict(syn[0], **{"판정자 구분": REVIEWER[1], "후보 판정": "정답"})]   # 전문가 검수 분리 확인용 1행
    p = OUT / "hitl_판정시트_v1_합성판정_자체시험.xlsx"
    write_sheet(syn, p, note_extra="※ 이 파일은 합성 판정값(무작위)으로 채운 자체 시험용이다. 실제 판정이 아니다.")
    res = cmd_aggregate(p, tag="_합성_자체시험")
    # 독립 계산과 대조
    mp = {m["판정ID"]: m for m in mapping["rows"]}
    ok = True
    for m in METHODS:
        mine = [r for r in syn if r["판정자 구분"] == REVIEWER[0] and m in mp[r["판정ID"]]["proposed_by"]]
        jd = [r for r in mine if r["후보 판정"]]
        exp = round(sum(r["후보 판정"] == "정답" for r in jd) / len(jd), 3) if jd else None
        got = res[REVIEWER[0]][m]["ratio_정답"]
        ok &= exp == got and res[REVIEWER[0]][m]["candidates"] == len(mine)
    ok &= res[REVIEWER[1]]["R_index_v2" if "R_index_v2" in mp[syn[0]["판정ID"]]["proposed_by"] else next(iter(mp[syn[0]["판정ID"]]["proposed_by"]))]["judged"] == 1
    ok &= all(res[REVIEWER[0]][m]["candidates"] == sum(m in x["proposed_by"] for x in mapping["rows"]) for m in METHODS)
    print("SELFTEST", "PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    a = sys.argv[1:] or ["build"]
    if a[0] == "build":
        cmd_build()
    elif a[0] == "aggregate":
        cmd_aggregate(Path(a[1]))
    elif a[0] == "selftest":
        cmd_selftest()
