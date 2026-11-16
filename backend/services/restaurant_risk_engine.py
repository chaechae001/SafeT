"""Deterministic ordinal policy, not a probability model or work permit.

Server must perform JSON Schema validation before calling evaluate().
Trusted input/registry must be server-owned, not supplied by the model.
"""
from copy import deepcopy
POLICY='RESTAURANT-3LEVEL-2.0'
MATRIX={1:{1:1,2:2,3:2},2:{1:2,2:2,3:3},3:{1:3,2:3,3:3}}
LABEL={1:'하',2:'중',3:'상',None:None}

def _unique(items, label):
    ids=[x['id'] for x in items]
    if len(ids)!=len(set(ids)): raise ValueError(f'duplicate {label} id')
    return set(ids)

def validate_semantics(analysis, input_data, catalog):
    """Cross-reference and policy guards beyond JSON Schema.

    Does not authenticate images, prove legal applicability, or verify real controls.
    Those require trusted preprocessing and human/functional verification.
    """
    if analysis['policy_version']!=POLICY: raise ValueError('policy mismatch')
    if analysis['assessment_id']!=input_data['assessment_id']: raise ValueError('assessment mismatch')
    mids=_unique(input_data['media'],'media')
    eids=_unique(analysis['evidence'],'evidence')
    hids=_unique(analysis['hazards'],'hazard')
    _unique(analysis['questions'],'question')
    _unique(analysis['actions'],'action')
    rids={r['id'] for r in catalog['rules']}
    registry={r['id']:r for r in input_data['trusted_legal_registry']}
    ev={e['id']:e for e in analysis['evidence']}
    def refs(ids):
        if not set(ids)<=eids: raise ValueError('unknown evidence id')
    for e in analysis['evidence']:
        if e['media_id'] not in mids: raise ValueError('unknown media id')
        loc=e['locator']; bbox=loc['bbox_xyxy_norm']
        if bbox is not None and (bbox[0]>=bbox[2] or bbox[1]>=bbox[3]): raise ValueError('invalid image box')
        start,end=loc['audio_start_ms'],loc['audio_end_ms']
        if (start is None)!=(end is None) or (start is not None and start>=end): raise ValueError('invalid audio interval')
        media=next(m for m in input_data['media'] if m['id']==e['media_id'])
        if bbox is not None and media['modality']!='photo': raise ValueError('image locator on non-photo')
        if start is not None and media['modality']!='voice_transcript': raise ValueError('audio locator on non-voice')
        if start is not None and media['transcript_segments'] and end>max(s['end_ms'] for s in media['transcript_segments']): raise ValueError('audio interval outside input')
    for m in input_data['media']:
        _unique(m['transcript_segments'],'transcript segment')
        if any(s['start_ms']>=s['end_ms'] for s in m['transcript_segments']): raise ValueError('invalid transcript interval')
    coverage=analysis['coverage']
    if len(coverage)!=len(rids) or {c['rule_id'] for c in coverage}!=rids:
        raise ValueError('all catalog families must have coverage status')
    if sum(q['first_batch'] for q in analysis['questions'])>5: raise ValueError('too many first questions')
    for q in analysis['questions']+analysis['actions']:
        if not set(q['hazard_ids'])<=hids: raise ValueError('unknown linked hazard')
    for h in analysis['hazards']:
        if not h['rule_ids'] or not set(h['rule_ids'])<=rids: raise ValueError('unknown rule')
        refs(h['evidence_ids']); refs(h['closure_evidence_ids'])
        if not set(h['related_hazard_ids'])<=hids: raise ValueError('unknown related hazard')
        if h['id'] in h['related_hazard_ids']: raise ValueError('self-related hazard')
        for key in ('severity_options','control_options'):
            options=h[key]
            if not options or any(type(x)!=int or x not in (1,2,3) for x in options) or len(options)!=len(set(options)):
                raise ValueError('invalid options')
        if h['applicability']=='confirmed':
            if not h['evidence_ids'] or not h['controls']: raise ValueError('confirmed hazard requires evidence and controls')
            if not any(ev[e]['kind']!='inference' and ev[e]['time_scope']=='current' for e in h['evidence_ids']):
                raise ValueError('confirmed hazard needs current non-inference evidence')
        if h['applicability'] in ('closed','not_applicable') and not h['closure_evidence_ids']:
            raise ValueError('closure/nonapplicability needs evidence')
        if h['applicability']=='closed' and not any(ev[e]['kind']!='inference' and ev[e]['time_scope']=='current' for e in h['closure_evidence_ids']):
            raise ValueError('closure needs current evidence')
        _unique(h['controls'],'control')
        for c in h['controls']:
            refs(c['evidence_ids'])
            if c['state'] not in ('unknown',) and not c['evidence_ids']:
                raise ValueError('asserted control state needs evidence')
        bad_critical=any(c['critical'] and c['state'] in ('absent','ineffective') for c in h['controls'])
        uncertain_critical=any(c['critical'] and (c['state']=='unknown' or (c['state']=='reported_effective' and c['verification_required'])) for c in h['controls'])
        derived_incomplete=(len(h['severity_options'])>1 or len(h['control_options'])>1 or bool(h['contradictions']) or uncertain_critical or any(c['state']=='unknown' for c in h['controls']))
        if h['applicability']=='confirmed' and derived_incomplete and h['decision_evidence_complete']:
            raise ValueError('incomplete evidence cannot be declared complete')
        if h['applicability']=='confirmed' and bad_critical and h['control_options']!=[3]:
            raise ValueError('known failed critical control requires C3')
        if h['applicability']=='confirmed' and uncertain_critical and not bad_critical and 3 not in h['control_options']:
            raise ValueError('unverified critical control must retain C3 possibility')
        if h['control_options']==[1] and h['applicability']=='confirmed':
            if any(c['state'] not in ('verified_effective','not_applicable') and not (c['state']=='reported_effective' and not c['verification_required']) for c in h['controls']):
                raise ValueError('C1 requires effective applicable controls')
        for key, flag in h['safety_flags'].items():
            refs(flag['evidence_ids'])
            if flag['value']=='yes' and not flag['evidence_ids']: raise ValueError('positive flag needs evidence')
            if flag['value']=='yes' and not any(ev[e]['kind']!='inference' for e in flag['evidence_ids']):
                raise ValueError('positive flag cannot rely only on inference')
            if key in ('imminent_danger','verified_legal_breach') and flag['value']=='yes':
                if h['applicability']!='confirmed': raise ValueError('confirmed override needs confirmed hazard')
                if not any(ev[e]['time_scope']=='current' for e in flag['evidence_ids']): raise ValueError('override needs current evidence')
        law=h['safety_flags']['verified_legal_breach']
        if law['value']=='yes' and (not law['registry_ids'] or not set(law['registry_ids'])<=set(registry)):
            raise ValueError('legal breach requires trusted verified registry')
        for lid in law['registry_ids']:
            if lid not in registry: raise ValueError('unknown registry id')
        for ref in h['source_refs']:
            source=next((s for s in catalog['sources'] if s['id']==ref['document_id']),None)
            if source is None or not any(lo<=ref['printed_page']<=hi for lo,hi in source['printed_ranges']): raise ValueError('source page outside reviewed scope')
            if ref['pdf_page']!=ref['printed_page']+source['pdf_offset']: raise ValueError('page offset mismatch')
        if h['applicability'] in ('possible','confirmed') and (not h['decision_evidence_complete'] or h['contradictions']):
            if not any(h['id'] in q['hazard_ids'] for q in analysis['questions']): raise ValueError('incomplete hazard needs question')

def grade_hazard(h):
    app=h['applicability']
    result={'hazard_id':h['id'],'status':{'possible':'candidate'}.get(app,app),'grade':None,'ordinal':None,'range':{'min':None,'max':None},'acceptability':'undetermined','rule_applied':[],'requires_human_review':True,'immediate_exposure_stop':False}
    if app in ('closed','not_applicable'):
        result['acceptability']='not_applicable'
        result['rule_applied']=['scenario_closed_or_not_applicable_with_evidence']
        return result
    if app=='possible':
        result['rule_applied']=['candidate_is_not_confirmed_hazard']
        return result
    values={MATRIX[s][c] for s in h['severity_options'] for c in h['control_options']}
    result['rule_applied']=['matrix_S_C']
    flags=h['safety_flags']
    forced=flags['imminent_danger']['value']=='yes' or flags['verified_legal_breach']['value']=='yes'
    if forced:
        values={3}
        if flags['imminent_danger']['value']=='yes': result['rule_applied'].append('confirmed_imminent_danger')
        if flags['verified_legal_breach']['value']=='yes': result['rule_applied'].append('verified_current_legal_breach')
    if flags['unresolved_same_cause_near_miss']['value']=='yes':
        values={max(v,2) for v in values}
        result['rule_applied'].append('unresolved_near_miss_floor_2')
    uncertain_control=any(c['state']=='unknown' or (c['critical'] and c['state']=='reported_effective' and c['verification_required']) for c in h['controls'])
    complete=(h['decision_evidence_complete'] and not h['contradictions'] and len(h['severity_options'])==1 and len(h['control_options'])==1 and not uncertain_control)
    low,high=min(values),max(values)
    result['range']={'min':low,'max':high}
    if forced: complete=True  # Validated decisive override alone establishes high; gaps remain in analysis.
    if not complete and high==1:
        result['status']='needs_information'
        result['rule_applied'].append('no_low_confirmation_with_missing_information')
        return result
    result['status']='confirmed' if complete else 'provisional'
    result['ordinal']=high
    result['grade']=LABEL[high]
    result['acceptability']='acceptable_in_assessed_scope' if complete and high==1 else 'not_acceptable'
    result['requires_human_review']=not complete or high==3
    result['immediate_exposure_stop']=flags['imminent_danger']['value']=='yes'
    if not complete: result['rule_applied'].append('provisional_max_of_possible_combinations')
    return result

def evaluate(analysis,input_data,catalog):
    validate_semantics(analysis,input_data,catalog)
    results=[grade_hazard(h) for h in analysis['hazards']]
    def maximum(status):
        vals=[r['ordinal'] for r in results if r['status']==status and r['ordinal'] is not None]
        return LABEL[max(vals)] if vals else None
    ordinals=[r['ordinal'] for r in results if r['ordinal'] is not None]
    summary={'max_confirmed':maximum('confirmed'),'max_provisional':maximum('provisional'),'assessed_scope_max':LABEL[max(ordinals)] if ordinals else None,'confirmed_counts':{g:sum(r['status']=='confirmed' and r['grade']==g for r in results) for g in ('상','중','하')},'provisional_counts':{g:sum(r['status']=='provisional' and r['grade']==g for r in results) for g in ('상','중','하')},'unrated_count':sum(r['grade'] is None and r['status'] not in ('closed','not_applicable') for r in results),'information_incomplete_count':sum(not h['decision_evidence_complete'] or bool(h['contradictions']) for h in analysis['hazards']),'site_safety_conclusion':'not_determined'}
    summary['coverage_needs_information_count']=sum(c['status']=='needs_information' for c in analysis['coverage'])
    return {'policy_version':POLICY,'assessment_id':analysis['assessment_id'],'analysis':deepcopy(analysis),'results':results,'summary':summary,'work_authorization':'not_issued'}
