"""위험요인 → 법령 조문 검색기(외부 모델·추가 패키지 없음).

모든 검색기는 조문 키('문서번호:제N조') 순위 목록을 돌려준다. 결과는 검색 후보이며 법령 적용 판단이 아니다.

R0  서비스 현재: authoring_rag가 legal_registry를 넘기지 않아 법령 후보가 항상 0건.
R1  기존 risk_law_search 키워드 경로 재현: 항 단위 TF-IDF(정규식 토큰), 벌칙 조문 감점, 조문 단위 최댓값.
R2  청킹 변경: 조문 단위 BM25, 조문 제목·장절 제목 가중.
R3  R2 + 메타데이터 필터: 위험 예방 조문이 아닌 문서·일반 조항 제외.
R4  R3 + 질의 확장: 카탈로그 키워드·조치 문구를 질의에 추가.
R5  R4 + 재순위: 질의와 조문 제목이 겹치는 조문을 앞으로.
"""
import math
import re
from collections import Counter, defaultdict

from ai.risk_law_search.textindex import TextIndex, regex_tokens

# R3 메타데이터 필터. 01 위험성평가 지침(절차 고시), 04 중대재해처벌법(경영책임자 의무 일반),
# 05 식품위생법(식품 위생)은 개별 위험요인의 예방 조치 조문이 아니라서 위험요인 검색 대상에서 뺀다.
EXCLUDED_DOCS = {"01", "04", "05"}
GENERAL_TITLES = re.compile(r"^(목적|정의|적용 ?범위|적용 ?제외|다른 법률과의 관계|규제의 재검토|벌칙|과태료|양벌규정|"
                            r"권한의 위임|.*수수료|청문|.*벌칙 적용에서의 공무원 의제)")
STOP = {"w:" + w for w in ("사업주", "근로자", "경우", "하여야", "한다", "있는", "등의", "등을", "다음", "각호", "해당")}


def article_key(u):
    return f"{u['doc_no']}:{u['article']}"


def current_units(units):
    return [u for u in units if not u["future_version"]]


def tokens(text):
    return [t for t in regex_tokens(text) if t not in STOP]


class R0Service:
    name = "R0 서비스 현재(legal_registry 없음)"

    def __init__(self, units):
        pass

    def rank(self, query, k=10, expansion=""):
        return []


class R1KeywordTfidf:
    """engine.py keyword 모드의 법령 점수와 같은 색인·감점(형태소 분석기 대신 정규식 토큰)."""
    name = "R1 기존 키워드(TF-IDF·항 단위)"
    PENALTY_TITLES = ("벌칙", "과태료", "양벌규정")

    def __init__(self, units):
        self.units = current_units(units)
        text = lambda u: " ".join(x for x in (u["law_name"], u["article_title"], u["heading"].split(" > ")[-1], u["search_text"]) if x)
        self.index = TextIndex([text(u) for u in self.units], regex_tokens)

    def rank(self, query, k=10, expansion=""):
        best = {}
        for i, s in self.index.scores(query).items():
            u = self.units[i]
            s *= 0.7 if u["article_title"] in self.PENALTY_TITLES else 1.0
            key = article_key(u)
            best[key] = max(best.get(key, 0.0), s)
        return [key for key, _ in sorted(best.items(), key=lambda x: (-x[1], x[0]))[:k]]


class BM25Articles:
    """조문 단위 BM25. 제목·장절 제목을 title_w배로 반복해 넣는다."""
    k1, b = 1.2, 0.75

    def __init__(self, units, title_w=3, filtered=False, expand=False, rerank=False, name=None):
        self.name = name or "BM25"
        self.expand, self.rerank = expand, rerank
        groups = defaultdict(list)
        for u in current_units(units):
            groups[article_key(u)].append(u)
        self.keys, docs, self.titles = [], [], []
        for key, us in groups.items():
            u = us[0]
            if filtered and (u["doc_no"] in EXCLUDED_DOCS or GENERAL_TITLES.match(u["article_title"] or "")):
                continue
            head = u["heading"].split(" > ")[-1] if u["heading"] else ""
            title = " ".join(x for x in (u["article_title"], head) if x)
            body = " ".join(x["search_text"] for x in us)
            self.keys.append(key)
            self.titles.append(set(tokens(u["article_title"] or "")))
            docs.append(Counter(tokens(title) * title_w + tokens(body)))
        self.docs = docs
        self.len = [sum(c.values()) for c in docs]
        self.avg = sum(self.len) / len(self.len)
        df = Counter()
        for c in docs:
            df.update(c.keys())
        n = len(docs)
        self.idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}
        self.post = defaultdict(list)
        for i, c in enumerate(docs):
            for t, f in c.items():
                self.post[t].append((i, f))

    def scores(self, query):
        acc = defaultdict(float)
        for t, qf in Counter(tokens(query)).items():
            idf = self.idf.get(t)
            if idf is None:
                continue
            for i, f in self.post[t]:
                norm = f * (self.k1 + 1) / (f + self.k1 * (1 - self.b + self.b * self.len[i] / self.avg))
                acc[i] += idf * norm * (1 + math.log(qf))
        return acc

    def rank(self, query, k=10, expansion=""):
        q = query + (" " + expansion if self.expand and expansion else "")
        acc = self.scores(q)
        if self.rerank and acc:
            qt = set(tokens(query))  # 제목 겹침은 확장 전 원 질의로만 본다(확장어 과적합 방지)
            top = max(acc.values())
            for i in list(acc):
                overlap = len(self.titles[i] & qt)
                if overlap:
                    acc[i] += top * 0.15 * min(overlap, 4)
        ranked = sorted(acc.items(), key=lambda x: (-x[1], self.keys[x[0]]))
        return [self.keys[i] for i, _ in ranked[:k]]


def build_all(units):
    return [
        R0Service(units),
        R1KeywordTfidf(units),
        BM25Articles(units, name="R2 조문 단위 BM25"),
        BM25Articles(units, filtered=True, name="R3 R2+메타데이터 필터"),
        BM25Articles(units, filtered=True, expand=True, name="R4 R3+질의 확장"),
        BM25Articles(units, filtered=True, expand=True, rerank=True, name="R5 R4+제목 재순위"),
    ]
