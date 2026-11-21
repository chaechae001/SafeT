"""TF-IDF 코사인 키워드 색인.

토큰화
- kiwi(기본, kiwipiepy 설치 시): 형태소 분석으로 조사·어미를 떼고 명사·동사·형용사 어간을 쓴다.
  예: '썰어요'·'썰기' → 동사 '썰', '넘어짐'·'넘어지거나' → '넘어지'. 2자 이상 명사는 글자 2개 조각도 더한다.
- regex(대체): 한글·영숫자 단어(2자 이상)와 단어 안 글자 2개 조각. kiwipiepy가 없을 때 쓴다.
점수는 0~1 코사인 유사도다. 검색 관련도이며 위험도나 법령 적용 판단이 아니다.
"""
import math
import re
from collections import Counter, defaultdict

WORD = re.compile(r"[0-9A-Za-z가-힣]+")
NOUN = {"NNG", "NNP", "NR", "XR", "SL", "SH"}
PRED = {"VV", "VA"}
# 어디에나 나오는 동사·형용사 어간. 이것만 겹쳐서 관련 있다고 보지 않도록 뺀다(예: '회의를 합니다'의 '하').
COMMON_PRED = {"하", "되", "있", "없", "같", "아니", "이"}


def regex_tokens(text):
    out = []
    for w in WORD.findall(text.lower()):
        if len(w) >= 2:
            out.append("w:" + w)
            out.extend("b:" + w[i:i + 2] for i in range(len(w) - 1))
    return out


class KiwiTokenizer:
    name = "kiwi"

    def __init__(self):
        from kiwipiepy import Kiwi
        self.kiwi = Kiwi()
        self.cache = {}

    def __call__(self, text):
        if text in self.cache:
            return self.cache[text]
        out = []
        for t in self.kiwi.tokenize(text.lower()):
            if t.tag in NOUN:
                out.append("n:" + t.form)
                if len(t.form) >= 2:
                    out.extend("b:" + t.form[i:i + 2] for i in range(len(t.form) - 1))
            elif t.tag in PRED and t.form not in COMMON_PRED:
                out.append("v:" + t.form)
            elif t.tag == "SN":
                out.append("d:" + t.form)
        if len(self.cache) < 20000:
            self.cache[text] = out
        return out

    def clause_cuts(self, text, endings):
        """나열형 연결 어미(endings) 바로 뒤의 글자 위치들. 뒤가 보조 용언('닦고 있어요')이면 자르지 않는다."""
        toks = self.kiwi.tokenize(text)
        return [t.start + t.len for t, nxt in zip(toks, toks[1:])
                if t.tag == "EC" and t.form in endings and nxt.tag != "VX"]

    def bare_noun(self, word):
        """조사·어미·동사 없이 명사(복합명사·접미사 포함)만으로 된 낱말인가. 예: '튀김기' 예, '바닥에' 아니오."""
        toks = self.kiwi.tokenize(word)
        return bool(toks) and all(t.tag in NOUN or t.tag in ("NNB", "XSN", "SN") for t in toks)


def make_tokenizer(prefer="kiwi"):
    """kiwi를 쓸 수 있으면 kiwi, 아니면 정규식 토큰화."""
    if prefer == "kiwi":
        try:
            return KiwiTokenizer()
        except ImportError:
            pass
    regex_tokens.name = "regex"
    return regex_tokens


class TextIndex:
    def __init__(self, texts, tokenizer=None):
        self.tokenize = tokenizer or regex_tokens
        self.n = len(texts)
        counts = [Counter(self.tokenize(t)) for t in texts]
        df = Counter()
        for c in counts:
            df.update(c.keys())
        self.idf = {t: math.log((1 + self.n) / (1 + d)) + 1.0 for t, d in df.items()}
        self.postings = defaultdict(list)
        for i, c in enumerate(counts):
            vec = {t: (1 + math.log(f)) * self.idf[t] for t, f in c.items()}
            norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
            for t, v in vec.items():
                self.postings[t].append((i, v / norm))

    def query_vector(self, text):
        c = Counter(self.tokenize(text))
        vec = {t: (1 + math.log(f)) * self.idf[t] for t, f in c.items() if t in self.idf}
        norm = math.sqrt(sum(v * v for v in vec.values())) or 1.0
        return {t: v / norm for t, v in vec.items()}

    def scores(self, text, allowed=None):
        """문서 번호 → 코사인 점수. allowed가 있으면 그 번호만 계산한다."""
        acc = defaultdict(float)
        for t, qv in self.query_vector(text).items():
            for i, dv in self.postings.get(t, ()):
                if allowed is None or i in allowed:
                    acc[i] += qv * dv
        return acc

    def search(self, text, k=10, allowed=None, min_score=0.0):
        ranked = sorted(self.scores(text, allowed).items(), key=lambda x: (-x[1], x[0]))
        return [(i, s) for i, s in ranked if s >= min_score][:k]
