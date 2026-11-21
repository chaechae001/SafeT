"""e5 임베딩 + LangChain Chroma 저장소.

- 모델: intfloat/multilingual-e5-small(기본). 문서는 'passage: ', 검색어는 'query: ' 접두어를 붙인다(e5 사용법).
- 저장: Chroma 영구 저장소(코사인). 컬렉션 이름에 모델·원문 지문을 넣어, 원문이나 모델이 바뀌면 새로 만든다.
- 점수: 저장된 벡터를 한 번 읽어 와 검색어 벡터와 내적(코사인)을 직접 계산한다.
  법령은 문서 번호 순서로 문서마다 관련 조문을 판단해야 해서 전체 점수가 필요하기 때문이다.
이 모듈은 sentence-transformers·langchain-chroma가 설치된 환경에서만 불러온다(requirements.txt).
"""
import hashlib
import json
import time
from pathlib import Path

from langchain_core.embeddings import Embeddings

DEFAULT_MODEL = "intfloat/multilingual-e5-small"
TEMPLATE = "t1"
BATCH = 256


class E5Embeddings(Embeddings):
    def __init__(self, model_name=DEFAULT_MODEL, device="cpu", batch_size=64):
        from sentence_transformers import SentenceTransformer
        self.model_name = model_name
        self.batch_size = batch_size
        self.model = SentenceTransformer(model_name, device=device)

    def embed_documents(self, texts):
        return self.model.encode(["passage: " + t for t in texts], batch_size=self.batch_size,
                                 normalize_embeddings=True, show_progress_bar=False).tolist()

    def embed_query(self, text):
        return self.embed_queries([text])[0]

    def embed_queries(self, texts):
        return self.model.encode(["query: " + t for t in texts], batch_size=self.batch_size,
                                 normalize_embeddings=True, show_progress_bar=False).tolist()


def fingerprint(model_name, ids, texts):
    h = hashlib.sha256(json.dumps([model_name, TEMPLATE], ensure_ascii=False).encode("utf-8"))
    for i, t in zip(ids, texts):
        h.update(i.encode("utf-8") + b"\0" + t.encode("utf-8") + b"\0")
    return h.hexdigest()


class SemanticIndex:
    """ids·texts 목록을 Chroma 컬렉션에 맞추고, 같은 순서의 벡터 행렬을 메모리에 둔다."""

    def __init__(self, prefix, ids, texts, metadatas, embeddings, persist_dir, log=print):
        import numpy as np
        from langchain_chroma import Chroma
        self.np = np
        self.fingerprint = fingerprint(embeddings.model_name, ids, texts)
        self.name = f"{prefix}_{self.fingerprint[:16]}"
        persist_dir = Path(persist_dir)
        persist_dir.mkdir(parents=True, exist_ok=True)
        self.store = Chroma(collection_name=self.name, embedding_function=embeddings,
                            persist_directory=str(persist_dir), collection_metadata={"hnsw:space": "cosine"})
        have = set(self.store.get(include=[])["ids"])
        missing = [k for k, i in enumerate(ids) if i not in have]
        self.built = bool(missing)
        if missing:
            t0 = time.time()
            log(f"{self.name}: {len(missing)}건 임베딩 중(CPU, 처음 한 번만)…")
            for s in range(0, len(missing), BATCH):
                part = missing[s:s + BATCH]
                self.store.add_texts([texts[k] for k in part], metadatas=[metadatas[k] for k in part],
                                     ids=[ids[k] for k in part])
            log(f"{self.name}: 임베딩 저장 {round(time.time() - t0, 1)}초")
        data = self.store.get(ids=list(ids), include=["embeddings"])
        pos = {i: k for k, i in enumerate(data["ids"])}
        self.matrix = np.asarray([data["embeddings"][pos[i]] for i in ids], dtype="float32")
        self.ids = list(ids)
        self._drop_stale(prefix)

    def _drop_stale(self, prefix):
        client = self.store._client  # 같은 접두어의 이전 판 컬렉션 정리
        for c in client.list_collections():
            name = getattr(c, "name", c)
            if name.startswith(prefix + "_") and name != self.name:
                client.delete_collection(name)

    def scores(self, query_vectors):
        """검색어 벡터 목록 → 각 검색어의 코사인 점수 목록(이 색인의 ids 순서)."""
        q = self.np.asarray(query_vectors, dtype="float32")
        return (q @ self.matrix.T).tolist()
