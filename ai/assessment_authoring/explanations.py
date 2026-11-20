"""검증된 입력·문헌·계산값으로 설명한다. 문헌 밖 사실은 생성하지 않는다."""
import re


def unique_texts(texts):
    seen = set()
    result = []
    for text in texts:
        key = re.sub(r'\s+', '', text)
        if key and key not in seen:
            seen.add(key)
            result.append(text)
    return result


def document_summaries(documents):
    groups = {}
    for doc in documents:
        details = doc.get('source_evidence') or []
        if not details:
            details = [dict(source_file='문장별 출처 연결 미확인', hazard_text=t,
                            source_id=', '.join(doc.get('source_ids', [])), pdf_pages=[], link_id='')
                       for t in doc.get('hazard_texts', [])]
        for detail in details:
            name = detail['source_file']
            group = groups.setdefault(name, dict(source_file=name, entries=[]))
            if detail not in group['entries']:
                group['entries'].append(dict(detail))
    for group in groups.values():
        texts = unique_texts(e['hazard_text'] for e in group['entries'])
        group['summary'] = '문헌에서 제시한 위험: ' + ' / '.join(texts)
        prevention = unique_texts(e.get('prevention_text', '') for e in group['entries'])
        group['prevention_summary'] = ' / '.join(prevention)
        group['reference_notice'] = '과거 발행 기술자료 · 현행 법령 검증 대상이 아님' if prevention else ''
        group['pdf_pages'] = sorted({p for e in group['entries'] for p in e.get('pdf_pages', [])})
        group['source_ids'] = list(dict.fromkeys(e['source_id'] for e in group['entries']))
    return list(groups.values())


def rationale(candidate, scenario, result, documents):
    quotes = unique_texts(e['statement'] for e in candidate['evidence'])
    intro = '입력의 ' + ' · '.join('“'+t+'”' for t in quotes) + ' 내용을 바탕으로 '
    texts = unique_texts(t for doc in documents for t in doc.get('hazard_texts', []))
    if texts:
        intro += '문헌에 제시된 ' + ' / '.join('“'+t+'”' for t in texts) + ' 위험을 후보에 포함했습니다. '
    else:
        intro += '카탈로그의 “'+scenario['title']+'” 위험을 후보에 포함했습니다. 직접 연결된 검색 문헌은 없습니다. '
    states = {e['control_id']:e['state'] for e in candidate['control_evidence']}
    critical = [c for c in scenario['controls'] if c['critical']]
    unknown = [c['current_text'] for c in critical if states[c['id']]=='unknown']
    ineffective = [c['current_text'] for c in critical if states[c['id']]=='not_effective']
    reasons = []
    if unknown: reasons.append('핵심 조치 중 '+', '.join(unknown)+'의 실시 여부가 입력에서 확인되지 않았습니다.')
    if ineffective: reasons.append('입력에서 '+', '.join(ineffective)+'의 미실시 또는 효과 부족이 확인됐습니다.')
    if result['control_band'] == 1:
        reasons.append('모든 기준 조치의 실시 근거가 확인됐습니다.')
    elif result['control_band'] == 2:
        reasons.append('핵심 조치는 확인됐으나 나머지 기준 조치 중 확인되지 않거나 효과가 부족한 항목이 있습니다.')
    reasons.append('시나리오의 피해 수준과 확인된 조치 상태에 기존 기준을 적용한 결과는 ‘'+result['grade']+'’입니다.')
    if 'unknown' in states.values():
        reasons.append('미확인은 계산에만 미충족으로 반영하며 실제 미실시로 단정하지 않습니다.')
    return intro + ' '.join(reasons)
