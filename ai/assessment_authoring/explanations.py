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


def control_details(candidate, scenario):
    """기준 조치마다 상태와 입력 원문을 연결한다. 미확인은 원문을 붙이지 않는다."""
    evidence = {e['control_id']: e for e in candidate['control_evidence']}
    details = []
    for control in scenario['controls']:
        e = evidence.get(control['id'], {})
        state = e.get('state', 'unknown')
        details.append(dict(control_id=control['id'], text=control['current_text'], critical=control['critical'],
                            state=state, statement=e.get('statement', '') if state != 'unknown' else '',
                            evidence_refs=list(e.get('evidence_refs', [])) if state != 'unknown' else []))
    return details


def rationale(candidate, scenario, result, documents):
    """입력에서 확인한 작업·조치와 등급 계산 이유만 쓴다. 문헌 내용은 문헌 근거 영역에서 표시한다."""
    quotes = unique_texts(e['statement'] for e in candidate['evidence'])
    parts = ['입력의 ' + ' · '.join('“'+t+'”' for t in quotes) + ' 내용에서 “' + scenario['task'] + '” 작업을 확인했습니다.']
    states = {e['control_id']: e['state'] for e in candidate['control_evidence']}
    supported = [c['current_text'] for c in scenario['controls'] if states.get(c['id']) == 'supported']
    ineffective = [c['current_text'] for c in scenario['controls'] if states.get(c['id']) == 'not_effective']
    unknown = [c['current_text'] for c in scenario['controls'] if c['critical'] and states.get(c['id'], 'unknown') == 'unknown']
    if supported: parts.append('입력에서 실시가 확인된 조치는 ' + ', '.join(supported) + '입니다.')
    if ineffective: parts.append('입력에서 ' + ', '.join(ineffective) + '의 고장·미실시 또는 효과 부족이 확인됐습니다.')
    if unknown: parts.append('핵심 조치 중 ' + ', '.join(unknown) + '의 실시 여부는 입력에서 확인되지 않았습니다.')
    if result['control_band'] == 1:
        parts.append('모든 기준 조치의 실시 근거가 확인됐습니다.')
    elif result['control_band'] == 2:
        parts.append('핵심 조치는 모두 확인됐으나 나머지 기준 조치 중 확인되지 않거나 효과가 부족한 항목이 있습니다.')
    parts.append('시나리오의 피해 수준과 확인된 조치 상태에 공통 기준을 적용한 현재 위험도는 ‘' + result['grade'] + '’입니다.')
    if 'unknown' in states.values() or unknown:
        parts.append('미확인은 계산에만 미충족으로 반영하며 실제 미실시로 단정하지 않습니다.')
    return ' '.join(parts)
