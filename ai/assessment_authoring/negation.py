"""형태소 분석(kiwipiepy) 기반 기기·작업 미사용 판정.

단어 순서를 그대로 기대하는 정규식 대신 문장을 절로 나누고, 기기·작업어가 속한 절에서
부정 표현이 그 기기·작업을 가리키는지 본다.

판정 규칙
1. 연결어미(고·지만·는데·서·며 등)와 종결어미로 절을 나눈다. 문장부호가 없는 음성 전사도
   종결어미("써요")에서 나뉜다.
2. 이유 절("고장 나서", "손님이 없어서")이 사용 서술어 없이 끝나면 다음 절까지 범위를 넓힌다.
3. 범위 안에 부정 표현(않·안·못·없·미사용)이 있고, 기기·작업어와 부정 사이에 다른 명사의
   주어·목적어·주제("온도 제어 장치가", "보호장갑을")가 없으면 미사용이다.
   - 않·안·못은 사용 서술어(사용·쓰다·돌리다·가동·켜다·하다·튀기다 등)를 함께 요구한다.
   - 없다·미사용은 기기·작업 자체의 부재로 본다("튀김기 없습니다", "쓸 일 없어요").
4. 기기·작업어가 다른 명사를 꾸미기만 하면("튀김기 기름을", "튀김기 주변에") 부정 대상이 아니다.
위험·조치 부정("온도 제어 장치가 작동하지 않습니다")은 다른 명사가 주어이므로 미사용이 아니다.
"""
from functools import lru_cache

_NOUN_TAGS = {"NNG", "NNP", "NNB", "NR", "NP", "SN", "SL", "XSN", "XPN"}
_ARG_PARTICLES = {"JKS", "JKO", "JX", "JKC"}
# 절을 나누는 연결어미. 부정 구성의 "지"·"게"는 나누지 않는다.
_CLAUSE_EC = {"고", "지만", "는데", "은데", "ᆫ데", "데", "며", "으며", "면서", "으면서", "어서", "아서", "서",
              "니까", "으니까", "니", "으니", "라서", "거나", "든지", "고서"}
_REASON_EC = {"어서", "아서", "서", "니까", "으니까", "니", "으니", "라서", "고서"}
# 사용 서술어: 동사 자체 또는 "명사+하다"의 명사.
_USE_VERBS = {"쓰", "사용하", "돌리", "켜", "하", "튀기", "가동하", "운영하", "굴리"}
_USE_NOUNS = {"사용", "가동", "운영", "작업", "조리"}
# 기기·작업어 뒤에 붙어도 부정 대상을 바꾸지 않는 명사(작업 이름, 시점).
_SAME_TARGET_NOUNS = {"작업", "조리", "사용", "가동", "일", "때", "오늘", "요즘", "당분간", "지금", "현재",
                      "평소", "이번", "주", "요새", "최근", "한동안",
                      "아침", "점심", "저녁", "밤", "낮", "오전", "오후", "평일", "주말", "매일"}

# 시점 명사. 명사구의 끝이 이것이면 시간 부사어로 본다.
_TIME_NOUNS = _SAME_TARGET_NOUNS - {"작업", "조리", "사용", "가동", "일"}


@lru_cache(maxsize=1)
def _kiwi():
    from kiwipiepy import Kiwi
    return Kiwi()


@lru_cache(maxsize=2048)
def _tokens(text):
    return tuple((t.form, t.tag, t.start, t.start + t.len) for t in _kiwi().tokenize(text))


def _clauses(tokens):
    """토큰 색인 범위 [start, end) 목록. 종결어미·문장부호·연결어미 뒤에서 나눈다."""
    out, start = [], 0
    for i, (form, tag, _, _) in enumerate(tokens):
        if tag in ("EF", "SF") or (tag == "EC" and form in _CLAUSE_EC):
            if i + 1 > start:
                out.append((start, i + 1))
            start = i + 1
    if start < len(tokens):
        out.append((start, len(tokens)))
    return out


def _is_use(tokens, i):
    form, tag = tokens[i][:2]
    if tag == "VV" and form in _USE_VERBS:
        return True
    return tag in ("NNG", "NNP") and form in _USE_NOUNS and i + 1 < len(tokens) and tokens[i + 1][1] == "XSV"


def _negation(tokens, i):
    """(부정 여부, 부재형 여부). 부재형(없다·미사용)은 사용 서술어 없이도 미사용이다."""
    form, tag = tokens[i][:2]
    if tag == "VA" and form == "없":
        return True, True
    if tag == "XPN" and form == "미" and i + 1 < len(tokens) and tokens[i + 1][0] in ("사용", "가동"):
        return True, True
    if (tag == "VX" and form in ("않", "못하")) or (tag == "MAG" and form in ("안", "못")):
        return True, False
    return False, False


def _noun_phrases(tokens, lo, hi):
    """[lo, hi) 안의 명사구: (시작, 끝, 뒤따르는 조사 태그 집합)."""
    out, i = [], lo
    while i < hi:
        if tokens[i][1] in _NOUN_TAGS:
            j = i
            while j < hi and tokens[j][1] in _NOUN_TAGS:
                j += 1
            k = j
            while k < hi and tokens[k][1].startswith("J"):
                k += 1
            out.append((i, j, {tokens[x][1] for x in range(j, k)}))
            i = k
        else:
            i += 1
    return out


def _head_eojeol(tokens, a, b):
    """명사구의 마지막 어절(띄어쓰기 단위) 토큰 범위."""
    h = b - 1
    while h > a and tokens[h - 1][3] == tokens[h][2]:
        h -= 1
    return h, b


def _is_argument(particles):
    return bool(particles & _ARG_PARTICLES) and not any(p.startswith("JKB") or p == "JKG" for p in particles)


def denied(text, start, end):
    """text[start:end]의 기기·작업어가 미사용·부재로 진술되었으면 True."""
    tokens = _tokens(text)
    term = [i for i, t in enumerate(tokens) if t[2] < end and t[3] > start]
    if not term:
        return False
    first, last = term[0], term[-1]
    # "안 튀겨요"처럼 기기·작업어가 사용 동사이고 바로 앞에 부정 부사가 오는 경우.
    if any(_is_use(tokens, x) and x > 0 and tokens[x - 1][:2] in (("안", "MAG"), ("못", "MAG")) for x in term):
        return True
    clauses = _clauses(tokens)
    c = next(n for n, (a, b) in enumerate(clauses) if a <= first < b)
    # 기기·작업어가 다른 명사를 꾸미면("튀김기 기름을", "튀김기의 온도") 부정 대상이 아니다.
    for a, b, particles in _noun_phrases(tokens, clauses[c][0], clauses[c][1]):
        if a <= first < b:
            h, _ = _head_eojeol(tokens, a, b)
            head_nouns = {tokens[x][0] for x in range(h, b)}
            if last < h and not head_nouns <= _SAME_TARGET_NOUNS:
                return False
            if "JKG" in particles:
                return False
            last = max(last, b - 1)
    scope = [(last + 1, clauses[c][1], True)]
    k = c
    while k + 1 < len(clauses) and tokens[clauses[k][1] - 1][0] in _REASON_EC \
            and tokens[clauses[k][1] - 1][1] == "EC" \
            and not any(_is_use(tokens, x) for x in range(*clauses[k])):
        k += 1
        scope.append((clauses[k][0], clauses[k][1], False))
    for lo, hi, has_term in scope:
        # "튀기지 않습니다"처럼 기기·작업어가 곧 사용 서술어일 수 있다.
        use = any(_is_use(tokens, x) for x in [*(term if has_term else []), *range(lo, hi)])
        # 다른 명사: 조사가 붙은 주어·목적어·주제는 모든 부정을, 조사 없는 명사("가스 누출 없음")는
        # 부재형 부정을 그 명사 쪽으로 돌린다.
        others = [(a, _is_argument(p)) for a, b, p in _noun_phrases(tokens, lo, hi)
                  if not {tokens[x][0] for x in range(a, b)} <= _SAME_TARGET_NOUNS]
        for x in range(lo, hi):
            neg, absence = _negation(tokens, x)
            if not neg or any(a < x and (argument or absence) for a, argument in others):
                continue
            if absence or use:
                return True
    return False


def resumed_without_subject(text, start, end):
    """미사용 진술 뒤에 주어·목적어 없이 사용 서술어만 있는 절이 이어지면 True.

    "튀김기는 점심에는 안 쓰고 저녁에만 써요"처럼 생략된 주어가 앞의 기기일 수 있다.
    이때 미사용으로 단정하지 않고 사람이 확인하도록 남긴다(보수 규칙).
    """
    tokens = _tokens(text)
    term = [i for i, t in enumerate(tokens) if t[2] < end and t[3] > start]
    if not term:
        return False
    clauses = _clauses(tokens)
    c = next(n for n, (a, b) in enumerate(clauses) if a <= term[0] < b)
    for lo, hi in clauses[c + 1:]:
        if any(_negation(tokens, x)[0] for x in range(lo, hi)):
            continue
        if not any(_is_use(tokens, x) for x in range(lo, hi)):
            continue
        # 시점 명사구("오후 장사 때만", "주말에만")와 작업 이름만인 명사구는 다른 대상이 아니다.
        # "철판 조리만"처럼 다른 작업을 가리키는 명사구는 다른 대상이다.
        explicit = [a for a, b, p in _noun_phrases(tokens, lo, hi)
                    if _is_argument(p) and tokens[b - 1][0] not in _TIME_NOUNS
                    and not {tokens[x][0] for x in range(a, b)} <= _SAME_TARGET_NOUNS]
        if not explicit:
            return True
    return False


# ---------------------------------------------------------------------------
# 확실·불확실 판정. 불확실한 판정은 규칙만으로 제외하지 않고 확인 후보로 두거나
# 선택적으로 언어 모델(negation_judge)의 확인을 받는다.

# 기기의 부품·연결부, 지시 대명사. 이것이 부정 대상이면 기기 미사용일 수 있으나 단정하지 않는다.
_PART_NOUNS = {"전원", "코드", "플러그", "스위치", "불", "밸브", "가스", "전기", "버너", "그거", "그것", "그건",
               "이거", "이것", "저거", "걔", "얘"}
# 끄기·치우기·중단처럼 부정어 없이 미사용을 뜻할 수 있는 동사(또는 "명사+하다"의 명사).
_OFF_VERBS = {"끄", "치우", "뽑", "잠그", "없애", "빼", "멈추", "놀리", "세우"}
_OFF_NOUNS = {"철거", "중단", "보관", "폐기", "정지", "휴업"}
_CONTRAST_EC = {"는데", "은데", "ᆫ데", "데", "지만"}
_MENU_HEADS = {"메뉴", "요리"}


def _is_off(tokens, i):
    form, tag = tokens[i][:2]
    if tag == "VV" and form in _OFF_VERBS:
        return True
    return tag in ("NNG", "NNP") and form in _OFF_NOUNS


def _negated_before(tokens, i, lo):
    """i번 동사가 "안 끄고"·"끄지 않고"처럼 부정되었는가."""
    if i > lo and tokens[i - 1][:2] in (("안", "MAG"), ("못", "MAG")):
        return True
    j = i + 1
    while j < len(tokens) and tokens[j][1] in ("XSV", "EC", "EP") and tokens[j][0] not in _CLAUSE_EC - {"지"}:
        j += 1
    return j < len(tokens) and _negation(tokens, j)[0] and not _negation(tokens, j)[1]


def judge(text, start, end):
    """text[start:end]의 기기·작업어 진술을 판정한다.

    반환: (verdict, certain, reason). verdict는 "used" 또는 "unused".
    certain=False인 판정은 규칙만으로 확정하지 않는다(확인 후보 또는 언어 모델 확인).
    """
    if denied(text, start, end):
        if resumed_without_subject(text, start, end):
            # "점심에는 안 쓰고 저녁에만 써요": 생략 주어가 앞 기기일 수 있다. 위험 쪽 오류를 막기 위해
            # 잠정 판정을 사용으로 둬, 모델 확인으로도 제외되지 않게 한다.
            return "used", False, "생략 주어 사용 절"
        return "unused", True, ""
    tokens = _tokens(text)
    term = [i for i, t in enumerate(tokens) if t[2] < end and t[3] > start]
    if not term:
        return "used", True, ""
    clauses = _clauses(tokens)
    c = next(n for n, (a, b) in enumerate(clauses) if a <= term[0] < b)
    lo, hi = clauses[c]
    last = term[-1]
    head = None
    for a, b, particles in _noun_phrases(tokens, lo, hi):
        if a <= term[0] < b:
            last, head = max(last, b - 1), tokens[b - 1][0]
    after = range(last + 1, hi)
    others = [tokens[b - 1][0] for a, b, p in _noun_phrases(tokens, last + 1, hi)
              if _is_argument(p) and tokens[b - 1][0] not in _SAME_TARGET_NOUNS]
    negs = [x for x in after if _negation(tokens, x)[0]]
    use = any(_is_use(tokens, x) for x in after)
    # "튀김 요리는 안 팔아요", "튀김 메뉴를 없앴어요": 메뉴·요리의 부재·중단.
    if head in _MENU_HEADS and (negs or any(_is_off(tokens, x) for x in after)):
        return "unused", False, "메뉴·요리 부정"
    # "튀김기 말고 오븐만 써요".
    if last + 1 < hi and tokens[last + 1][:2] == ("말", "VV"):
        return "unused", False, "말고 대체"
    # "튀김기 그거 안 써요", "튀김기 전원을 안 켜요": 부정 대상이 대명사·부품.
    # 부품·대명사 밖의 다른 대상("교체를 안 했어요")이 있으면 그 대상의 부정이다.
    if (head in _PART_NOUNS or others) and set(others) <= _PART_NOUNS and negs and use:
        return "unused", False, "부품·대명사 부정"
    # "튀김기는 전원을 꺼 놨어요", "튀김기를 아예 치웠습니다": 부정어 없는 미사용 동사.
    offs = [x for x in after if _is_off(tokens, x) and not _negated_before(tokens, x, last + 1)]
    if offs and set(others) <= _PART_NOUNS:
        return "unused", False, "끄기·치우기 동사"
    # "튀김기가 있긴 한데 안 써요", "튀김기는 있지만 안 씁니다": 대조 연결 뒤 주어 없는 부정.
    if tokens[hi - 1][1] == "EC" and tokens[hi - 1][0] in _CONTRAST_EC and c + 1 < len(clauses) and not negs:
        lo2, hi2 = clauses[c + 1]
        explicit = [a for a, b, p in _noun_phrases(tokens, lo2, hi2)
                    if _is_argument(p) and tokens[b - 1][0] not in _SAME_TARGET_NOUNS]
        if not explicit and any(_negation(tokens, x)[0] for x in range(lo2, hi2))                 and any(_is_use(tokens, x) or _negation(tokens, x)[1] for x in range(lo2, hi2)):
            return "unused", False, "대조 연결 뒤 부정"
    return "used", True, ""


def verb_at(text, start, lemma):
    """text의 start 위치에서 시작하는 형태소가 동사(VV) lemma인가."""
    return any(form == lemma and tag == "VV" and s == start for form, tag, s, _ in _tokens(text))
