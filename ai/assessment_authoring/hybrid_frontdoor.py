"""Per-work-unit hybrid retrieval for the input-based assessment."""
import copy
import json
import os
import re
from pathlib import Path

import numpy as np
import torch
from transformers import AutoModel, AutoTokenizer

from ai.assessment_authoring.live_text_check import input_segments
from ai.risk_law_search.cards import card_search_text
from ai.risk_law_search.engine import Engine
from ai.risk_law_search.scenario_map import ScenarioLinker, scenario_text
from ai.risk_law_search.textindex import TextIndex

# Outcome compatibility prevents a food-specific example from mapping an injury to another hazard family.
FAMILIES = (
    (re.compile('근골격계'), {'MSD'}),
    (re.compile('떨어짐|추락'), {'LADDER','LIFT'}),
    (re.compile('넘어짐|미끄러짐'), {'ENV'}),
    (re.compile('끼임|말림'), {'CUT','MIX','LIFT'}),
    (re.compile('베임|절단'), {'KNIFE','CUT'}),
    (re.compile('감전'), {'ELECT'}),
    (re.compile('화재|폭발'), {'FIRE','GAS'}),
)
ALIASES = {
    'ENV':'응축수 결로 누수 웅덩이 얼음 물기 출입 통행 미끄러짐',
    'MSD':'무거운 통이나 상자를 혼자 들어 올려 옮김 차량 적재 큰 용기 반복 들기',
    'LADDER':'박스 상자 의자 발판 위를 밟고 올라섬 떨어짐 추락',
    'CUT':'동력 컨베이어 벨트 롤러 가동부 끼임 회전부 걸린 물건 제거 정지 후 재가동',
    'MIX':'반죽 날 축 회전부 손 진입 청소 재가동',
    'WASH':'세척기 증기 뜨거운 물 세척액 비산',
    'ELECT':'젖은 손으로 플러그 전선 콘센트 접속 누전 감전',
}

class HybridFrontDoor:
    def __init__(self, repo, snapshot, catalog):
        torch.set_num_threads(min(4,os.cpu_count() or 1))
        self.tokenizer=AutoTokenizer.from_pretrained(snapshot,local_files_only=True)
        self.model=AutoModel.from_pretrained(snapshot,local_files_only=True).eval()
        self.engine=Engine(Path(repo)/'docs/chroma', mode='keyword', as_of='2026-11-24', log=lambda _:None)
        self.cards=self.engine.search_cards
        self.linker=ScenarioLinker()
        self.scenarios=list(catalog['scenarios'])
        self.by_id={s['id']:s for s in self.scenarios}
        self.card_index=self.embed([card_search_text(c) for c in self.cards],'passage: ')
        corpus=[scenario_text(s)+' '+ALIASES.get(s['id'],'') for s in self.scenarios]
        self.scenario_index=self.embed(corpus,'passage: ')
        self.scenario_keywords=TextIndex(corpus,self.engine.tokenizer)

    def embed(self,texts,prefix):
        groups=[]
        for start in range(0,len(texts),32):
            batch=self.tokenizer([prefix+t for t in texts[start:start+32]],return_tensors='pt',padding=True,truncation=True,max_length=256)
            with torch.inference_mode():
                hidden=self.model(**batch).last_hidden_state
                mask=batch['attention_mask'].unsqueeze(-1)
                pooling=(hidden*mask).sum(1)/mask.sum(1)
                groups.append(torch.nn.functional.normalize(pooling,p=2,dim=1).numpy())
        return np.concatenate(groups)

    @staticmethod
    def ranks(semantic,sparse):
        dense=np.argsort(-semantic,kind='stable')
        combined=1/(20+np.argsort(dense)+1)
        for rank,i in enumerate(sorted(sparse,key=lambda i:(-sparse[i],i)),1):
            if sparse[i]>0:
                combined[i]+=1/(20+rank)
        return list(np.argsort(-combined,kind='stable'))

    def rank_units(self, context, denied):
        segments={k:(media,re.sub(r'^\s*(?:치킨집 상황\.\s*|한편 다른 작업 구역에서는 다음 상황이 있습니다\.\s*)','',t)) for k,(media,t) in input_segments(context).items()}
        segments={k:(m,t) for k,(m,t) in segments.items() if t}
        if not segments:
            return []
        units=self.embed([text for _,text in segments.values()],'query: ')
        result=[]
        for key,(_,text),q in zip(segments,segments.values(),units):
            expanded,_=self.engine.expand(text)
            card_rank=self.ranks(q@self.card_index.T,self.engine.card_index.scores(expanded))[:5]
            scenario_rank=self.ranks(q@self.scenario_index.T,self.scenario_keywords.scores(expanded))
            order={self.scenarios[i]['id']:j for j,i in enumerate(scenario_rank)}
            mapped={}
            for k,i in enumerate(card_rank):
                c=self.cards[i]
                link=self.linker.for_card(c['id'])
                family=set().union(*(allowed for rx,allowed in FAMILIES if rx.search(c['risk_type'] or '')))
                ids=[row['scenario_id'] for row in link.get('candidates',[]) if not family or row['scenario_id'] in family]
                if link.get('status')=='confirmed':
                    ids=[link['scenario_id']]
                elif link.get('status')=='no_scenario':
                    ids=[]
                elif family and not ids:
                    ids=sorted(family & self.by_id.keys(),key=order.__getitem__)[:1]
                for sid in ids:
                    if sid not in order or sid in denied: continue
                    score=1/(21+k)+1/(21+order[sid])
                    if sid not in mapped or score>mapped[sid][0]:mapped[sid]=(score,c['id'])
            picked=sorted(mapped,key=lambda sid:(-mapped[sid][0],order[sid],sid))[:5]
            for i in scenario_rank:
                sid=self.scenarios[i]['id']
                if len(picked)==5:break
                if sid not in denied and sid not in picked:picked.append(sid)
            result.append(dict(ref=key,text=text,scenario_ids=picked,cards=[self.cards[i]['id'] for i in card_rank],provenance={sid:mapped[sid][1] for sid in picked if sid in mapped}))
        return result


    def augment(self, context, bundle, trace):
        existing = {row["scenario_id"] for row in bundle["candidates"]}
        denied = set(trace.get("not_applicable_candidates", []))
        for unit in self.rank_units(context, denied):
            for scenario_id in unit["scenario_ids"]:
                if scenario_id in existing:
                    continue
                refs = copy.deepcopy(self.by_id[scenario_id].get("source_refs", [])[:2])
                bundle["candidates"].append(dict(
                    scenario_id=scenario_id, source_refs=refs, legal_refs=[],
                    retrieval_status="matched" if refs else "no_evidence",
                ))
                existing.add(scenario_id)


GENERATION_GUIDELINES = '\n## 입력 근거 검증과 과잉 제외 방지\n- 동일 작업을 뜻하는 현장 표현은 정규화한다. 응축수 흔적 위를 통행하면 바닥 수분에 노출된 근거로 본다. 박스를 밟고 올라가면 물건을 임시 발판으로 사용한 근거다.\n- 카드에 쓰인 사례명과 입력의 대상 이름이 다르더라도, 입력에 같은 작업 동작·원인이 있고 해당 후보 시나리오의 적용 범위가 같으면 인정한다. 폐유통을 혼자 들어 옮기는 사례에 밥솥·무게를 덧붙이지 않는다.\n- 정지와 재가동 차단을 구분한다. 정지된 컨베이어의 끼인 물건을 손으로 빼고 잠금·전원 격리가 미확인이라면 재가동 끼임 가능성을 인정하고 잠금 여부를 가정 사항으로 둔다. 작동 중이라고 단정하지 않는다.\n- 복합 입력은 실제 작업별로 각각 평가한다. 한 문단의 부정이나 기기 상태를 다른 문단에 확대하지 않는다.\n- 튀김기 미사용과 밀봉 봉투 수량 확인을 근거로 튀김 화상과 칼 베임을 만들지 않는다. 사고 경험이 없다는 진술은 명시된 현재 작업을 부정하지 않는다.\n- 근거가 확인되는 후보만 기존 candidates에 넣는다. 그 위험이 실제 입력에 있으나 맞는 시나리오가 없으면 unmatched_risks에 남긴다. 후보가 없으면 기존 JSON 계약의 빈 배열을 반환한다. 법령과 등급을 새로 만들어 출력하지 않는다.\n\n이 규칙의 출력 키는 위의 compact JSON 계약을 따른다. work_ref는 input_segments 키이고 사고 원인과 작업이 확인될 때만 출력한다. 후보가 없으면 {"candidates":[]}를 돌려주고, 없는 ID 또는 필드를 만들지 않는다.\n후보 시나리오의 기존 작업명이 좁으면 같은 사고 기전을 검토한다. CUT는 채소 절단 외에 식기세척기 컨베이어·롤러 등 회전 구동부 접촉과, 전원 격리 근거가 없는 정지 설비에서 끼인 물건을 제거할 때의 재가동 끼임까지 포함한다. 작업이나 실제 재가동을 지어내지는 않는다. LADDER는 계단·사다리뿐 아니라 박스나 의자를 밟고 올라가는 행위의 추락을 포함한다. MSD는 큰 용기를 혼자 들거나 차량에 싣는 작업의 무리한 힘을 포함한다. ENV는 물기, 응축수 흔적, 기름이나 얼음 위 통행에서 미끄러지는 위험을 포함한다. 사진·보유·검색 제안은 작업 증거가 아니다. 입력에 사건 가능성을 뒷받침하는 work_ref가 없으면 제외한다.'

def strengthen_generation_prompt(messages):
    messages[0]["content"] = messages[0]["content"].replace(
        "후보 작업이 입력에서 실제로 수행되거나 해당 작업의 잠재 위험이면 candidates에 넣는다.",
        "실제로 수행하는 작업과 해당 사고 원인을 둘 다 뒷받침하는 입력이 있는 후보만 candidates에 넣는다.",
    ) + GENERATION_GUIDELINES + (
        "\nscenario_id는 한 번씩만 출력한다. 여러 문장이 같은 위험이면 가장 직접적인 작업 문장 하나를 선택한다."
        "\n보유·미사용·사용 여부 미확인 문장만으로는 위험을 채택하지 않는다."
        "\n간헐 조리와 실제 기름 교체는 각각 작업이다. 검색 카드나 다른 작업의 위험을 옮겨 적지 않는다."
    )
    payload = json.loads(messages[1]["content"])
    for candidate in payload["candidate_scenarios"]:
        if candidate["id"] == "CUT":
            candidate["risk_scope"] = (
                "절단·회전체 및 컨베이어 끼임. 정지 후 잠금이 확인되지 않은 "
                "청소·막힘 제거의 재가동 가능성을 포함."
            )
    messages[1]["content"] = json.dumps(payload, ensure_ascii=False)
