"""B 경로(비교용): #45(ai/legal_review) 법령 찾기 방식을 우리 법령 원문으로 재현한다.

A(기본)는 카드–법령 자동 연결(engine.py)이다. B는 서버 옵션 --law-alt kure45로만 켜지며 A를 바꾸지 않는다.

- 재현한 것(pr/45 ai/legal_review/worker.py, backend/services/legal_review.py 기준)
  - 질문 = '작업 위험요인제목 원인'. 우리 결과에서는 작업 = 입력 단위 문장, 제목 = 카드 제목, 원인 = 카드 본문.
  - KURE-v1, 첫 토큰(CLS) 벡터 정규화, 최대 512토큰, 접두어 없음, 임베딩 점수만 사용.
  - 전체 순위 → (법령명, 제N조) 단위 중복 제거 → 상위 6개.
- 다른 것
  - 원문: #45의 L01(청크 267개, 구성·청킹 미공개) 대신 우리 파서(laws.py)의 시행 중 항 단위 조각.
  - 청크 본문 = '법령명 조문위치 조문제목' + 원문(가정). Chroma 대신 numpy 내적(정규화 벡터라 순위 동일).
  - #45의 EXAONE 근거 판정은 없다(실제 모델 호출 중단 상태). 결과는 검색 후보다.
- 인덱스: ai/risk_law_search/.index/l01_kure/ (Git 제외). 만들기: python -m ai.risk_law_search.server --build-alt-index
"""
import json
import re
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
INDEX_DIR = HERE / ".index" / "l01_kure"
MODEL = "nlpai-lab/KURE-v1"
TOP = 6
LABEL = "#45 방식(KURE-v1 검색 · AI 판정 없음)"


def chunk_text(u):
    return f"{u['law_name']} {u['locator']} {u['article_title']}\n{u['quote']}"


class Encoder:
    def __init__(self, threads=8):
        import torch
        from transformers import AutoModel, AutoTokenizer
        self.torch = torch
        torch.set_num_threads(threads)
        self.tok = AutoTokenizer.from_pretrained(MODEL)
        self.model = AutoModel.from_pretrained(MODEL).eval()

    def __call__(self, texts, batch=16, log=None):
        import numpy as np
        torch = self.torch
        order = sorted(range(len(texts)), key=lambda i: len(texts[i]))  # 길이순으로 묶어 패딩을 줄인다
        vecs = [None] * len(texts)
        with torch.inference_mode():
            for s in range(0, len(order), batch):
                idx = order[s:s + batch]
                t = self.tok([texts[i] for i in idx], truncation=True, max_length=512, padding=True, return_tensors="pt")
                v = torch.nn.functional.normalize(self.model(**t).last_hidden_state[:, 0]).numpy()
                for k, i in enumerate(idx):
                    vecs[i] = v[k]
                if log and s // batch % 20 == 0:
                    log(f"  {s + len(idx)}/{len(texts)}")
        return np.asarray(vecs, dtype="float32")


def build(engine, index_dir=INDEX_DIR, log=print):
    """엔진의 시행 중 법령 조각으로 인덱스를 만든다."""
    import numpy as np
    units = [engine.units[i] for i in engine.law_pos]
    rows = [dict(chunk_id=u["id"], law=u["law_name"], doc_no=u["doc_no"], article=u["article"], section=u["locator"],
                 text=chunk_text(u)) for u in units]
    t0 = time.time()
    mat = Encoder()([r["text"] for r in rows], log=log)
    index_dir = Path(index_dir)
    index_dir.mkdir(parents=True, exist_ok=True)
    np.save(index_dir / "vectors.npy", mat)
    (index_dir / "chunks.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
    (index_dir / "meta.json").write_text(json.dumps(dict(model=MODEL, chunks=len(rows), as_of=engine.as_of,
                                                         seconds=round(time.time() - t0, 1)), ensure_ascii=False),
                                         encoding="utf-8")
    log(f"저장: {index_dir} ({len(rows)}개, {time.time() - t0:.0f}초)")


class KureLawFinder:
    name = "kure45"

    def __init__(self, engine, index_dir=INDEX_DIR, encoder=None):
        import numpy as np
        index_dir = Path(index_dir)
        if not (index_dir / "vectors.npy").exists():
            raise FileNotFoundError(f"B 경로 인덱스가 없습니다: {index_dir} (--build-alt-index로 먼저 만드세요)")
        meta = json.loads((index_dir / "meta.json").read_text(encoding="utf-8"))
        rows = json.loads((index_dir / "chunks.json").read_text(encoding="utf-8"))
        if meta.get("model") != MODEL:
            raise ValueError(f"인덱스 모델이 {MODEL}가 아닙니다.")
        # 법령 원문·평가일이 바뀌면 조각이 달라진다. 섞어 쓰지 않도록 조각 ID 순서까지 확인한다.
        if [r["chunk_id"] for r in rows] != [engine.units[i]["id"] for i in engine.law_pos]:
            raise ValueError("법령 조각이 인덱스와 다릅니다(원문·평가일 변경). --build-alt-index로 다시 만드세요.")
        self.np, self.engine, self.rows, self.meta = np, engine, rows, meta
        self.mat = np.load(index_dir / "vectors.npy")
        self.encoder = encoder or Encoder(threads=4)

    @staticmethod
    def question(text, card):
        return " ".join(x for x in (text, card["title"], card["text"]) if x)

    def find(self, text, card, top=TOP):
        q = self.question(text, card)
        scores = self.mat @ self.encoder([q])[0]
        out, seen = [], set()
        for i in self.np.argsort(-scores):
            r = self.rows[i]
            m = re.match(r"제\d+조(?:의\d+)?", r["section"])
            key = (r["law"], m.group() if m else r["section"])
            if key in seen:
                continue
            seen.add(key)
            out.append(self.engine.law_view(r["chunk_id"], float(scores[i]), dict(semantic=round(float(scores[i]), 3), keyword=None)))
            if len(out) == top:
                break
        return dict(method=self.name, label=LABEL, question=q, candidates=out,
                    note="검색 후보입니다. #45의 AI 근거 판정은 적용하지 않았습니다. 적용 여부는 담당자가 확인합니다.")

    def info(self):
        return dict(method=self.name, label=LABEL, model=MODEL, chunks=len(self.rows), built_as_of=self.meta.get("as_of"))
