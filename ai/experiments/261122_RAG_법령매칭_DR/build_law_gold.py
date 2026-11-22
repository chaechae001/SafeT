"""위험요인 ID별 법령 정답셋을 만든다.

입력
- law_gold_spec.json: 시나리오별 기대 조문 번호와 근거 유형(사람이 적은 명세)
- chroma/laws/*.hwpx: 보유 법령 원문(조문 존재·제목·발췌를 여기서 채운다)
- contracts/catalog_risk/catalog.json: 시나리오 source_refs(문서 B 쪽)
- 261115_RAG_법령검증목록_v1_DR.json: 문서가 실제로 인용한 조문과 인용 위치

출력: 261122_RAG_법령정답셋_v1_DR.json
원문에 없는 조문, 쪽이 맞지 않는 source_cited 근거가 있으면 실패한다.

  python ai/experiments/261122_RAG_법령매칭_DR/build_law_gold.py
"""
import hashlib
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT))
from ai.risk_law_search.laws import load_laws  # noqa: E402

SPEC = HERE / "law_gold_spec.json"
OUT = HERE / "261122_RAG_법령정답셋_v1_DR.json"
VERIFIED = ROOT / "ai/experiments/261115_RAG_지식베이스_DR/261115_RAG_법령검증목록_v1_DR.json"
CATALOG = ROOT / "contracts/catalog_risk/catalog.json"
LAW_DIR = ROOT / "chroma/laws"
CHUNK_PAGE = re.compile(r"^D5-p(\d{3})-")
# 문서 B(서비스업 재해사례 중심 안내서)가 RAG 청크의 D5와 같은 파일이다(제목·쪽 오프셋 8 일치).
CATALOG_DOC_FOR_D5 = "B"


def sha256(path):
    """파일 해시. JSON·텍스트는 줄바꿈을 LF로 맞춰 OS별 체크아웃(CRLF/LF)과 무관하게 같은 값을 낸다."""
    data = Path(path).read_bytes()
    if Path(path).suffix.lower() in {".json", ".jsonl", ".md", ".txt"}:
        data = data.replace(b"\r\n", b"\n")
    return hashlib.sha256(data).hexdigest()


def split_of(sid):
    """시나리오 ID 해시로 고정 분할. 개선 규칙은 dev만 보고 정하고 holdout은 최종 확인에만 쓴다."""
    return "holdout" if int(hashlib.sha1(sid.encode()).hexdigest(), 16) % 2 else "dev"


def article_index(units):
    out = {}
    for u in units:
        if u["future_version"]:
            continue
        key = f"{u['doc_no']}:{u['article']}"
        out.setdefault(key, []).append(u)
    return out


def main():
    spec = json.loads(SPEC.read_text(encoding="utf-8"))
    docs, units = load_laws(LAW_DIR)
    arts = article_index(units)
    doc_by_no = {d["doc_no"]: d for d in docs}
    catalog = json.loads(CATALOG.read_text(encoding="utf-8-sig"))
    scen = {s["id"]: s for s in catalog["scenarios"]}
    verified = json.loads(VERIFIED.read_text(encoding="utf-8"))
    cited = {}
    for v in verified["verified"]:
        if v["law_name"] == "산업안전보건기준에 관한 규칙":
            for c in v["cited_in"]:
                cited.setdefault("02:" + v["article"], set()).add(c.get("chunk_id"))
    errors = []
    if set(spec["scenarios"]) != set(scen):
        errors.append(f"시나리오 불일치: 명세에만 {sorted(set(spec['scenarios']) - set(scen))}, 카탈로그에만 {sorted(set(scen) - set(spec['scenarios']))}")
    items = []
    for sid in sorted(spec["scenarios"]):
        s = spec["scenarios"][sid]
        b_pages = {r["pdf_page"] for r in scen[sid]["source_refs"] if r["document_id"] == CATALOG_DOC_FOR_D5}
        row = dict(scenario_id=sid, title=scen[sid]["title"], status=s["status"], split=split_of(sid),
                   note=s.get("note"), core=[], related=[])
        for level in ("core", "related"):
            for e in s.get(level, []):
                key = e["key"]
                no, art = key.split(":")
                if no not in doc_by_no:
                    errors.append(f"{sid} {key}: 보유 원문에 없는 문서")
                    continue
                entry = dict(key=key, basis=e["basis"], law_name=doc_by_no[no]["law_name"],
                             law_edition=doc_by_no[no]["edition"], note=e.get("note"))
                if art != "*":
                    found = arts.get(key)
                    if not found:
                        errors.append(f"{sid} {key}: 원문에서 조문을 찾지 못함")
                        continue
                    entry.update(article_title=found[0]["article_title"],
                                 excerpt=found[0]["search_text"][:160],
                                 unit_ids=[u["id"] for u in found])
                if "source_cited" in e["basis"]:
                    chunk = e.get("cited_chunk")
                    m = CHUNK_PAGE.match(chunk or "")
                    if not m or chunk not in cited.get(key, set()):
                        errors.append(f"{sid} {key}: 법령검증목록 cited_in에 {chunk} 없음")
                    elif int(m[1]) not in b_pages:
                        errors.append(f"{sid} {key}: 인용 쪽 p{m[1]}이 시나리오 문서 B 쪽 {sorted(b_pages)}에 없음")
                    entry["cited_chunk"] = chunk
                row[level].append(entry)
        if s["status"] == "평가" and not row["core"]:
            errors.append(f"{sid}: 평가 대상인데 core 조문 없음")
        items.append(row)
    if errors:
        raise SystemExit("정답셋 검증 실패\n" + "\n".join(errors))
    evaluated = [r for r in items if r["status"] == "평가"]
    out = dict(
        version="law-gold-v1", built_by="build_law_gold.py", retrieved_or_built="2026-11-22 (Asia/Seoul)",
        status="AI 보조 정답 · 담당자 검토 전. source_cited만 출처 문서가 직접 인용한 조문이다.",
        sources=dict(spec=dict(file=SPEC.name, sha256=sha256(SPEC)),
                     law_verification=dict(file=VERIFIED.relative_to(ROOT).as_posix(), sha256=sha256(VERIFIED),
                                           retrieved_date=verified["retrieved_date"], site=verified["source_site"]),
                     catalog=dict(file=CATALOG.relative_to(ROOT).as_posix(), policy=catalog["policy_version"], sha256=sha256(CATALOG)),
                     laws=[dict(doc_no=d["doc_no"], law_name=d["law_name"], edition=d["edition"], file=d["file"], sha256=d["sha256"]) for d in docs]),
        rules=spec["_levels"], basis=spec["_basis"],
        counts=dict(scenarios=len(items), evaluated=len(evaluated), unverified=len(items) - len(evaluated),
                    core=sum(len(r["core"]) for r in evaluated),
                    core_source_cited=sum(1 for r in evaluated for e in r["core"] if "source_cited" in e["basis"]),
                    dev=sum(1 for r in evaluated if r["split"] == "dev"),
                    holdout=sum(1 for r in evaluated if r["split"] == "holdout")),
        items=items)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(out["counts"], ensure_ascii=False))
    for r in evaluated:
        print(r["split"], r["scenario_id"], [e["key"] for e in r["core"]])


if __name__ == "__main__":
    main()
