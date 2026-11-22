"""기기·작업 미사용(부정문) 판정 변형 회귀셋을 만든다. 모든 문장은 합성 데이터다.

기본 문장(사용·미사용·위험/조치 부정·연결 절) × 변형(장소, 수식어, 시점, 이유, 구어 어미,
문장부호 없는 음성 전사)을 조합한다. 조합은 고정 시드로 고른다.

기대값
- FRY: [튀김 후보(hit), 튀김 미사용 표시(denied)]. 사용 [True, False], 미사용 [False, True],
  위험·조치 부정 [True, False](미사용이 아님), 사용·미사용 혼재 [True, True].
- MIX·GRIDDLE: 글 후보 여부(hit). 이 둘은 미사용 표시가 없다.

  python ai/experiments/261123_미사용판정_형태소_DR/build_negation_set.py
"""
import itertools
import json
import random
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
OUT = HERE / "261123_미사용판정_변형셋_v1_DR.json"
SEED = 261123
PER_TEMPLATE = 5

SLOTS = dict(
    loc=["", "1층 주방에서 "],
    mod=["", "전기 ", "가스 ", "큰 "],
    time=["", "요즘 ", "당분간 "],
    reason=["", "고장 나서 "],
)

USED, UNUSED, HAZARD, MIXED = [True, False], [False, True], [True, False], [True, True]

# (분류, 기본 문장, FRY 기대값, 다른 시나리오 기대 hit)
TEMPLATES = [
    # 사용
    ("사용", "{loc}{mod}튀김기를 {time}사용합니다.", USED, {}),
    ("사용", "{loc}{mod}튀김기로 {time}감자를 튀깁니다.", USED, {}),
    ("사용", "{loc}{mod}튀김기를 {time}돌려요.", USED, {}),
    ("사용", "{loc}{time}돈가스를 튀기는 일을 합니다.", USED, {}),
    # 미사용
    ("미사용", "{loc}{mod}튀김기는 {time}{reason}사용하지 않습니다.", UNUSED, {}),
    ("미사용", "{loc}{mod}튀김기는 {time}{reason}안 써요.", UNUSED, {}),
    ("미사용", "{loc}{mod}튀김기는 {time}{reason}안 돌려요.", UNUSED, {}),
    ("미사용", "{loc}{mod}튀김기는 {time}{reason}쓸 일 없어요.", UNUSED, {}),
    ("미사용", "{loc}{time}튀김은 {reason}안 해요.", UNUSED, {}),
    ("미사용", "{loc}{time}{reason}튀기지 않습니다.", UNUSED, {}),
    ("미사용", "{loc}{mod}튀김기를 {time}{reason}가동하지 않습니다.", UNUSED, {}),
    ("미사용", "{mod}튀김기는 {time}안 써요. 볶음만 해요.", UNUSED, {}),
    # 위험·조치 부정: 기기를 쓰면서 장치·조치가 빠진 상태이므로 미사용이 아니다.
    ("위험부정", "{loc}{mod}튀김기의 온도 제어 장치가 작동하지 않습니다.", HAZARD, {}),
    ("위험부정", "{loc}{mod}튀김기 주변에 소화기가 없습니다.", HAZARD, {}),
    ("위험부정", "{loc}{mod}튀김기를 쓸 때 보호장갑을 {time}착용하지 않습니다.", HAZARD, {}),
    ("위험부정", "{loc}{mod}튀김기 기름을 {time}자주 갈지 않습니다.", HAZARD, {}),
    # 연결 절(~지 않고, ~지만)
    ("연결", "{mod}튀김기는 {time}사용하지 않고 반죽기만 사용합니다.", UNUSED, {"MIX": True}),
    ("연결", "{mod}튀김기는 {time}쓰지 않지만 그리들은 매일 씁니다.", UNUSED, {"GRIDDLE": True}),
    ("연결", "반죽기는 {time}안 쓰고 {mod}튀김기만 돌려요.", USED, {"MIX": False}),
    ("연결", "튀김기는 2층에서 가동하지만 {loc}{mod}튀김기를 가동하지 않습니다.", MIXED, {}),
    # 다른 기기
    ("다른기기", "{loc}반죽기는 {time}{reason}안 돌려요.", [False, False], {"MIX": False}),
    ("다른기기", "{loc}반죽기로 {time}면 반죽을 합니다.", [False, False], {"MIX": True}),
]


def voice(text):
    """문장부호를 지운 음성 전사 형태. 구어 군말 '음'을 앞에 붙인다."""
    return "음 " + re.sub(r"[.,!?]", "", text).strip()


def main():
    rng = random.Random(SEED)
    items = []
    for t_no, (category, template, fry, others) in enumerate(TEMPLATES, 1):
        names = [n for n in SLOTS if "{" + n + "}" in template]
        combos = [dict(zip(names, values)) for values in itertools.product(*(SLOTS[n] for n in names))]
        picked = [combos[0]] + rng.sample(combos[1:], min(PER_TEMPLATE - 1, len(combos) - 1))
        for combo in picked:
            text = template.format(**combo)
            for kind, value in (("text", text), ("voice_transcript", voice(text))):
                items.append(dict(id=f"T{t_no:02d}-{len(items) + 1:03d}", template=t_no, category=category,
                                  kind=kind, text=value, variants={k: v.strip() for k, v in combo.items() if v},
                                  expected=dict(FRY=fry, **others)))
    out = dict(version="negation-variants-v1", built_by="build_negation_set.py", seed=SEED,
               note="합성 데이터. 실제 사용자 발화가 아니며 현장 판정 정확도로 해석하지 않는다.",
               expected_format="FRY=[hit, denied], 그 외 시나리오=hit", count=len(items), items=items)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(len(items))


if __name__ == "__main__":
    main()
