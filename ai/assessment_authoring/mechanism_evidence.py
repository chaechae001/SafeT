"""Check the accident mechanism against each cited work sentence."""
import re

from .retrieval_adapter import _mentions

# Each group must match within the same citation. Alternatives inside a group
# describe different ways to state the same part of the mechanism.
_RULES = {
    "ENV": (r"바닥|통로|경사로|노면|매트|배수구|단차|문턱|계단|응축수", r"물기|젖|흘(?:러|렀)|미끄|기름기|응축수|얼음|걸려|걸릴|들뜬|눕혀|적치|방치"),
    "LADDER": (r"사다리|발판|의자|계단|(?:상자|박스).{0,10}(?:밟|올라)", r"오르|올라|밟|내려|오르내|휘청|흔들|떨어|균형|몸이 돌아|발.{0,3}헛"),
    "TRANS": (r"대차|카트|운반차|바스켓|운반물|폐기물 통", r"기울|넘어|굴러|부딪|충돌|떨어|빠질|넘치|손잡이.{0,12}풀"),
    "STORAGE": (r"적재|선반|쌓|용기|박스|필터", r"기울|떨어|걸쳐|위태|쏟|같이 움직|머리 위.{0,16}넘겨"),
    "COLD": (r"냉동|냉장", r"갇|문이.{0,12}안 열|탈출|저온.{0,15}노출"),
    "KNIFE": (r"칼|도마|커터|칼날", r"잡|베|찔|썰|자르|잘라|손질|떼|씻|빠졌|가려|거품|미끄"),
    "KNIFE_STORAGE": (r"칼|칼집|칼날", r"보관|수납|꽂|빼|거품|싱크대"),
    "UV": (r"자외선|살균(?:기|등)|UV", r"노출|쬐|눈|피부|켜진 채"),
    "CUT": (r"절단기|육절기|톱니|회전|롤러|컨베이어|셔터|팬|구동부|가동부|기계", r"끼|말려|재가동|다시 켜|절단|손을 넣|손으로 빼|가까이 대|손을 놓"),
    "MIX": (r"반죽기|혼합기|회전부|축|팬", r"끼|말|긁|가까이|손.{0,12}넣|멈추기 전|다시 켜"),
    "RICE": (r"밥솥|취반|솥", r"증기|뜨겁|뜨거|김이|화상"),
    "GAS": (r"가스|LPG|연소|버너", r"누출|새|냄새|불완전|폭발|점화"),
    "KETTLE": (r"솥|냄비", r"뜨겁|뜨거|끓", r"기울|쏟|엎|넘어|미끄"),
    "GRIDDLE": (r"철판|그리들|구이판", r"고온|뜨거|달군|화상"),
    "OVEN": (r"오븐|트레이", r"증기|열기|뜨거|화상|달군"),
    "VENT": (r"환기|후드|배기|흄|연소가스", r"부족|꺼져|고장|안 되|흡입|쌓|밀폐"),
    "SERVE": (r"뜨거|끓|잔열|달군", r"음식|양념|접시|쟁반|그릇|용기|냄비", r"비산|튀|운반|옮|떨어|쏟|접촉|부딪"),
    "LIFT": (r"승강기|승강로|리프트", r"끼|추락|문.{0,8}열|탑승|방호"),
    "DELIVERY": (r"오토바이|차량|이륜차|도로", r"후진|충돌|부딪|전도|미끄|급정거"),
    "WASH": (r"세척기|세척실|세척|식기", r"증기|뜨거|김이|고온|세정액|세척액|세제.{0,12}(?:튐|튀|닿)"),
    "CHEM": (r"세정제|세제|표백제|화학|염소|산성", r"혼합|함께|섞|분사|분무|닿|흡입|마셔|오인|음료병|표시 없이"),
    "ELECT": (r"전선|콘센트|멀티탭|플러그|전원|충전부", r"젖|물기|물이.{0,15}닿|피복.{0,15}(?:벗|손상)|누전|금속.{0,12}접촉|감전"),
    "FIRE": (r"과열|계속 끓|불꽃|불이.{0,5}붙|착화|탄.{0,4}냄새|연기가.{0,4}나|폭발|가열.{0,20}종이|후드.{0,15}기름때|불.{0,15}기름때",),
    "MSD": (r"무거|중량|반복|오래|오랜|장시간|한 시간|허리|어깨|손목|혼자|연달아|무리|비튼", r"들|꺼내|옮|들어|숙|버무|밀|당|자세|버텨|올려"),
    "PSYCH": (r"폭언|폭행|괴롭힘|과도한 업무|정신건강",),
}

def supports(scenario_id, statement):
    if scenario_id == "FRY":
        from .fryer_work import decide
        state, _ = decide({"media": [{"id": "work", "kind": "text", "text": statement}]})
        return state == "used"
    groups = _RULES.get(scenario_id)
    if not groups:
        return False
    for group in groups:
        if not any(verdict == "used" or not certain
                   for term in re.findall(group, statement) if term
                   for _, _, verdict, certain, _ in _mentions(statement, (term,))):
            return False
    return True

def filter_candidates(analysis):
    kept = []
    for row in analysis["candidates"]:
        citations = [quote for quote in row["evidence"] if supports(row["scenario_id"], quote["statement"])]
        if citations:
            kept.append(dict(row, evidence=citations))
    return dict(analysis, candidates=kept)
