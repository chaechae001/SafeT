"""ERD V1.1 평가표 작성/저장/확정. 트랜잭션·소유권·revision·상태 잠금."""
import json
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, OperationalError
from services.auth import AuthError, now
from services import workplaces, assessment_provider as provider
from services import catalog_risk as catalog
from services import authoring_rag


def rows(db, sql, **p): return [dict(r) for r in db.execute(text(sql),p).mappings()]
def execute(db, sql, **p): return db.execute(text(sql),p)
def locked_rows(db, sql, **params):
    """쓰기 전 최초 잠금만 재시도한다. 이미 수행한 쓰기나 AI 호출은 반복하지 않는다."""
    for attempt in range(2):
        try:
            return rows(db, sql, **params)
        except OperationalError as exc:
            code = exc.orig.args[0] if exc.orig.args else None
            if code not in (1020, 1205, 1213):
                raise
            db.rollback()
            if code != 1020 or attempt:
                raise AuthError(409, 'CONCURRENT_CHANGE', '다른 요청이 자료를 변경했어요. 새로 불러와 주세요.') from None


def owned(db, email, no, lock=False):
    sql="SELECT * FROM eval_mst WHERE eval_no=:n AND email=:e AND COALESCE(del_yn,'N')='N'" + (' FOR UPDATE' if lock else '')
    r=(locked_rows if lock else rows)(db,sql,n=no,e=email)
    if not r: raise AuthError(404,'EVAL_NOT_FOUND','평가표를 찾을 수 없어요.')
    return r[0]

def writable(m,revision):
    if m['eval_status']!='W': raise AuthError(409,'EVAL_LOCKED','확정된 평가표는 수정할 수 없어요.')
    if m['revision']!=revision: raise AuthError(409,'STALE_REVISION','다른 화면에서 저장했어요. 내용을 복사한 뒤 새로 불러와 주세요.')

def detail(db,email,no):
    m=owned(db,email,no)
    members=rows(db,'SELECT member_nm FROM eval_member WHERE eval_no=:n ORDER BY sort,member_no',n=no)
    result={k:m[k] for k in ('eval_no','work_no','eval_nm','eval_writer','eval_dt','eval_status','confirm_dt','revision','generation_source')}
    result['members']=[r['member_nm'] for r in members]
    w=rows(db,'SELECT workplace FROM workplaces WHERE work_no=:n',n=m['work_no'])
    result['workplace']=w[0]['workplace'] if w else ''
    result['machines']=rows(db,'SELECT machine_code,machine_nm FROM eval_machine WHERE eval_no=:n ORDER BY eval_machine_no',n=no)
    result['inputs']=rows(db,'SELECT file_type,ori_file_nm,place_nm,file_text FROM eval_file WHERE eval_no=:n AND eval_dtl_no IS NULL ORDER BY file_no',n=no)
    result['items']=[]
    for r in rows(db,'SELECT * FROM eval_dtl WHERE eval_no=:n ORDER BY sort,eval_dtl_no',n=no):
        it=dict(id=r['eval_dtl_no'],job=r['job'],factor=r['risk_factor'],title=r['risk_factor'],type=r['risk_type'],
            desc=r['reason'],cause=r['reason'],signal=r['curr_risk_grade'] or 'N',reason=r['risk_reason'],
            law=dict(name=r['law'],summary=r['law_summary'],url='https://www.law.go.kr/') if r['law'] else None,
            none=r['curr_none_yn']=='Y',keep=r['keep_yn'],
            owner=dict(type=r['manager_type'],name=r['manager_nm']) if r['manager_nm'] else None,
            due=r['due_dt'].isoformat() if r['due_dt'] else '',after=r['after_risk_grade'] or 'N',judged=r['after_judge_yn']=='Y',curr=[],plans=[])
        for a in rows(db,'SELECT * FROM eval_action WHERE eval_dtl_no=:n ORDER BY sort,action_no',n=it['id']):
            it['curr' if a['action_type']=='C' else 'plans'].append(dict(id=a['action_no'],text=a['action_text'],checked=a['check_yn']=='Y',ai=a['ai_yn']=='Y'))
        catalog.enrich(it, r.get('catalog_state'))
        authoring_rag.enrich(it, it.get('catalog'))
        result['items'].append(it)
    if m['generation_source'] == authoring_rag.SOURCE:
        saved = json.loads(m.get('authoring_snapshot') or '{}')
        snapshot = (result['items'][0]['authoring'] if result['items']
                    else saved)
        latest_review = max((it['work_review'] for it in result['items'] if it.get('work_review')),
                            key=lambda review: review['revision'], default={})
        result.update(excluded_review_candidates=saved.get('excluded_review_candidates',
                                                           latest_review.get('excluded_candidates', [])),
                      assessment_mode='input_based', result_status=snapshot['result_status'],
                      review_candidates=snapshot.get('review_candidates', []),
                      base_policy_version=snapshot.get('base_policy_version'),
                      unmatched_risks=snapshot['unmatched_risks'])
    return result

def insert_items(db,no,items,email,offset=0):
    for i,it in enumerate(items):
        result=execute(db,"INSERT INTO eval_dtl (eval_no,job,risk_factor,risk_type,reason,curr_risk_grade,risk_reason,curr_none_yn,keep_yn,after_risk_grade,after_judge_yn,sort,ins_dt,ins_nm) VALUES (:n,:j,:f,:ty,:c,:s,:r,'N',NULL,'N','N',:o,:t,:e)",n=no,j=it['job'],f=it['title'],ty=it['type'],c=it['cause'],s=it['signal'],r=it['reason'],o=offset+i,t=now(),e=email)
        for kind,values in (('C',it['curr']),('P',it['plans'])):
            for k,value in enumerate(values):
                execute(db,"INSERT INTO eval_action (eval_dtl_no,action_type,action_text,check_yn,ai_yn,sort) VALUES (:d,:k,:t,'N','Y',:s)",d=result.lastrowid,k=kind,t=value,s=k)
        if it.get('catalog'): catalog.initialize(db,result.lastrowid,it['catalog'],it.get('ai_analysis'))
        if it.get('authoring'): authoring_rag.initialize(db,result.lastrowid,it['authoring'])

def create(db,email,body):
    key=str(body.request_key)
    old=rows(db,'SELECT eval_no FROM eval_mst WHERE email=:e AND request_key=:k',e=email,k=key)
    if old: return detail(db,email,old[0]['eval_no'])
    w=workplaces.get_workplace(db,email,body.work_no)
    context=body.model_dump(); context['machines']=w['machines']
    use_catalog=catalog.enabled()
    use_authoring=authoring_rag.enabled()
    snapshot=catalog.list_catalog(db) if use_catalog or use_authoring else []
    # 외부 호출 전에 읽기 트랜잭션도 종료한다.
    db.rollback()
    if use_authoring:
        source, items, authoring_snapshot = authoring_rag.generate(snapshot, context)
    else:
        source, items = catalog.generate_snapshot(snapshot, context) if use_catalog else provider.generate(context)
    try:
        locked_rows(db,'SELECT work_no FROM workplaces WHERE work_no=:n FOR UPDATE',n=body.work_no)
        old=rows(db,'SELECT eval_no FROM eval_mst WHERE email=:e AND request_key=:k',e=email,k=key)
        if old: return detail(db,email,old[0]['eval_no'])
        fresh=workplaces.get_workplace(db,email,body.work_no)
        if any(fresh[k]!=w[k] for k in ('workplace','biz_code','machines')):
            raise AuthError(409,'WORKPLACE_CHANGED','분석 중 사업장 정보가 변경됐어요. 다시 확인해 주세요.')
        r=execute(db,"INSERT INTO eval_mst (work_no,email,eval_nm,eval_writer,eval_dt,eval_status,del_yn,request_key,revision,generation_source,ins_dt,ins_nm,upt_dt,upt_nm) VALUES (:w,:e,:nm,:writer,:dt,'W','N',:key,1,:src,:t,:e,:t,:e)",w=body.work_no,e=email,nm=f"{body.eval_dt} {w['workplace']} 위험성평가",writer=body.eval_writer,dt=body.eval_dt,key=key,src=source,t=now())
        no=r.lastrowid
        if use_authoring and not items:
            execute(db, 'UPDATE eval_mst SET authoring_snapshot=:s WHERE eval_no=:n',
                    s=json.dumps(authoring_snapshot, ensure_ascii=False), n=no)
        for i,name in enumerate(body.members): execute(db,'INSERT INTO eval_member (eval_no,member_nm,sort) VALUES (:n,:name,:i)',n=no,name=name,i=i)
        for machine in w['machines']: execute(db,"INSERT INTO eval_machine (eval_no,machine_code,machine_nm,ai_yn,check_yn) VALUES (:n,:c,:name,'N','Y')",n=no,c=machine['machine_code'],name=machine['machine_nm'])
        for kind,content in (('T',body.text),('V',body.voice_text)):
            if content: execute(db,'INSERT INTO eval_file (eval_no,file_type,file_text) VALUES (:n,:k,:t)',n=no,k=kind,t=content)
        for photo in body.photos: execute(db,"INSERT INTO eval_file (eval_no,file_type,ori_file_nm,place_nm,file_text) VALUES (:n,'P',:name,:place,:data)",n=no,name=photo.name,place=photo.place,data=photo.data)
        insert_items(db,no,items,email)
        db.commit()
    except IntegrityError:
        db.rollback()
        old=rows(db,'SELECT eval_no FROM eval_mst WHERE email=:e AND request_key=:k',e=email,k=key)
        if old: return detail(db,email,old[0]['eval_no'])
        raise
    except Exception:
        db.rollback();raise
    return detail(db,email,no)

def validation(items):
    errors=[]
    if not items: errors.append(dict(index=0,field='items',message='위험 항목이 없어요.'))
    for i,it in enumerate(items):
        def add(field,message): errors.append(dict(index=i,field=field,message=message))
        if it.get('assessment_mode') != 'input_based' and not it['none'] and not any(a['checked'] for a in it['curr']): add('current','현재 조치를 선택하거나 현재 조치 없음을 체크해 주세요.')
        if it['signal']=='N': add('signal','위험 신호 판단이 필요해요.')
        if it['signal']=='G' and it['keep'] not in ('Y','N'): add('plan','현재 상태 유지 또는 대책 추가를 선택해 주세요.')
        need=it['signal'] in ('R','Y') or (it['signal']=='G' and it['keep']=='N')
        if need:
            if not any(a['checked'] for a in it['plans']): add('plan','개선대책을 선택해 주세요.')
            if not it['owner'] or not it['due']: add('owner','담당자와 예정일을 지정해 주세요.')
    return errors

def save(db,email,no,body,confirm=False):
    try:
        m=owned(db,email,no,True); writable(m,body.revision)
        old=detail(db,email,no); originals={it['id']:it for it in old['items']}
        ids=[it.id for it in body.items]
        if len(ids)!=len(set(ids)) or set(ids)!=set(originals): raise AuthError(400,'INVALID_ITEMS','평가표 항목이 일치하지 않아요. 다시 불러와 주세요.')
        if old.get('review_candidates') and not originals:
            if confirm:
                raise AuthError(422, 'NO_ASSESSED_ROWS', '평가 항목이 없어 확정할 수 없습니다.')
            if body.excluded_review_candidates:
                raise AuthError(422, 'NO_ASSESSED_ROWS', '평가 항목이 없는 초안은 검토 후보로 보관합니다.')
        if m['generation_source'] == authoring_rag.SOURCE:
            pending = {candidate['scenario_id'] for candidate in old['review_candidates']}
            exclusions = set(old['excluded_review_candidates'] if body.excluded_review_candidates is None
                             else body.excluded_review_candidates)
            if not exclusions <= pending or (confirm and exclusions != pending):
                raise AuthError(422, 'CANDIDATE_REVIEW_REQUIRED',
                                '실제 작업이거나 아직 확인하지 않은 후보가 있어 확정을 보류합니다.')
            if body.excluded_review_candidates is not None and pending:
                execute(db, "UPDATE eval_mst SET authoring_snapshot=JSON_SET(COALESCE(authoring_snapshot,'{}'),"
                            "'$.excluded_review_candidates',JSON_EXTRACT(:x,'$')) WHERE eval_no=:n",
                        x=json.dumps(sorted(exclusions)), n=no)
        for edit in body.items:
            orig=originals[edit.id]
            if m['generation_source'] == authoring_rag.SOURCE:
                authoring_rag.protect_current(orig, edit)
                if confirm and not edit.work_reviewed:
                    raise AuthError(422, 'WORK_REVIEW_REQUIRED', '각 작업과 입력 근거를 확인해 주세요.')
                if edit.work_reviewed:
                    review = dict(reviewer=email, revision=body.revision+1, reviewed_at=str(now()),
                                  excluded_candidates=sorted(exclusions))
                    execute(db, "UPDATE eval_dtl SET catalog_state=JSON_SET(catalog_state,'$.work_review',JSON_EXTRACT(:r,'$')) WHERE eval_dtl_no=:n",
                            r=json.dumps(review,ensure_ascii=False), n=edit.id)
                else:
                    execute(db, "UPDATE eval_dtl SET catalog_state=JSON_REMOVE(catalog_state,'$.work_review') WHERE eval_dtl_no=:n", n=edit.id)
            # 기준 후보 문구·출처는 서버에서 관리하며 직접 추가 항목만 자유 입력을 허용한다.
            for kind,edits in (('C',edit.curr),('P',edit.plans)):
                original=orig['curr' if kind=='C' else 'plans']; byid={a['id']:a for a in original}
                used=set()
                for pos,a in enumerate(edits):
                    if a.id is not None:
                        if a.id in used or a.id not in byid or a.text!=byid[a.id]['text']: raise AuthError(400,'INVALID_ACTION','조치 정보가 일치하지 않아요.')
                        used.add(a.id)
                        execute(db,'UPDATE eval_action SET check_yn=:c,sort=:s WHERE action_no=:n',c='Y' if a.checked else 'N',s=pos,n=a.id)
                    else:
                        execute(db,"INSERT INTO eval_action (eval_dtl_no,action_type,action_text,check_yn,ai_yn,sort) VALUES (:d,:k,:t,:c,'N',:s)",d=edit.id,k=kind,t=a.text,c='Y' if a.checked else 'N',s=pos)
                for a in original:
                    if a['id'] not in used:
                        if a['ai']: raise AuthError(400,'INVALID_ACTION','추천 조치는 삭제할 수 없어요. 선택을 해제해 주세요.')
                        execute(db,'DELETE FROM eval_action WHERE action_no=:n',n=a['id'])
            if edit.owner and edit.owner.type=='R' and edit.owner.name not in [old['eval_writer'],*old['members']]:
                raise AuthError(400,'INVALID_OWNER','등록된 사람 목록에 없는 담당자예요.')
            execute(db,'UPDATE eval_dtl SET curr_none_yn=:none,keep_yn=:keep,manager_type=:mt,manager_nm=:mn,due_dt=:due,upt_dt=:t,upt_nm=:e WHERE eval_dtl_no=:n',none='Y' if edit.none else 'N',keep=edit.keep,mt=edit.owner.type if edit.owner else None,mn=edit.owner.name if edit.owner else None,due=edit.due,n=edit.id,t=now(),e=email)
        if m['generation_source'] in catalog.SOURCES:
            for edit in body.items: catalog.recalculate(db,originals[edit.id],edit,email,body.revision+1,no)
        updated=detail(db,email,no)
        if confirm:
            errors=validation(updated['items'])
            if errors: raise AuthError(422,'EVAL_INCOMPLETE','필수 항목을 확인해 주세요.',errors=errors)
        for it in updated['items']:
            if m['generation_source'] in (*catalog.SOURCES, authoring_rag.SOURCE): continue
            grade,judged=provider.project(it,m['generation_source'])
            execute(db,'UPDATE eval_dtl SET after_risk_grade=:g,after_judge_yn=:j WHERE eval_dtl_no=:n',g=grade,j='Y' if judged else 'N',n=it['id'])
        execute(db,'UPDATE eval_mst SET revision=revision+1,eval_status=:s,confirm_dt=:c,upt_dt=:t,upt_nm=:e WHERE eval_no=:n',s='C' if confirm else 'W',c=now() if confirm else None,t=now(),e=email,n=no)
        db.commit()
        return detail(db,email,no)
    except Exception:
        db.rollback(); raise

def add_risk(db,email,no,body):
    try:
        m=owned(db,email,no); writable(m,body.revision)
        if m['generation_source']==authoring_rag.SOURCE:
            raise AuthError(409,'AUTHORING_ADD_UNSUPPORTED','이 평가표의 위험 항목은 저장된 입력 분석 결과로 유지합니다. 새 작업은 새 평가표로 작성해 주세요.')
        data=detail(db,email,no)
        if len(data['items'])>=100: raise AuthError(400,'ITEM_LIMIT','최대 100개 항목까지 추가할 수 있어요.')
        # 서버 모드가 바뀌어도 기존 평가표의 생성 출처를 변경하지 않는다.
        if m['generation_source'] in catalog.SOURCES:
            from services.catalog_ai import restore_input
            snapshot=catalog.list_catalog(db)
            db.rollback()
            source,items=catalog.generate_snapshot(snapshot,restore_input(data),body.keyword,source=m['generation_source'])
            existing={it['catalog']['scenario']['id'] for it in data['items'] if it.get('catalog')}
            items=[it for it in items if it['catalog']['id'] not in existing]
            if not items: raise AuthError(409,'DUPLICATE_RISK','이미 추가된 DB 위험요인입니다.')
            if len(data['items'])+len(items)>100: raise AuthError(400,'ITEM_LIMIT','최대 100개 항목까지 추가할 수 있어요.')
        else:
            db.rollback()
            source,items=provider.generate(data,body.keyword)
        if source!=m['generation_source']: raise AuthError(409,'PROVIDER_CHANGED','생성 모드가 바뀌었어요. 기존 평가표의 출처를 유지해야 합니다.')
        current=owned(db,email,no,True);writable(current,body.revision)
        if current['generation_source']!=m['generation_source']:
            raise AuthError(409,'PROVIDER_CHANGED','평가표 생성 기준이 변경됐어요.')
        insert_items(db,no,items,email,len(data['items']))
        execute(db,'UPDATE eval_mst SET revision=revision+1,upt_dt=:t WHERE eval_no=:n',n=no,t=now())
        db.commit(); return detail(db,email,no)
    except Exception:
        db.rollback(); raise


def answer_risks(db,email,no,body):
    """현재 초안의 질문만 재분석한다. 기존 위험·선택·담당·계획은 보존한다."""
    from services import catalog_ai
    from schemas.assessment import ItemEdit
    try:
        m=owned(db,email,no);writable(m,body.revision)
        if m['generation_source']!=catalog.AI_SOURCE:
            raise AuthError(409,'AI_MODE_REQUIRED','AI로 생성한 초안에서만 답변을 반영할 수 있어요.')
        doc=detail(db,email,no)
        prior=[it['catalog']['ai_analysis'] for it in doc['items']]
        allowed={(it['id'],q['id']):q['text'] for it in doc['items'] for q in it['catalog']['ai_analysis']['questions']}
        submitted={(a.item_id,a.question_id) for a in body.answers}
        if len(submitted)!=len(body.answers) or submitted-allowed.keys():
            raise AuthError(422,'INVALID_ANSWERS','현재 평가표의 질문과 답변을 다시 확인해 주세요.')
        if any(it['catalog']['scenario']['policy_version']!=catalog.POLICY for it in doc['items']):
            raise AuthError(409,'POLICY_CHANGED','이전 기준 평가표입니다. 새 평가표를 작성해 주세요.')
        histories={it['id']:list(it['catalog'].get('answers',[])) for it in doc['items']}
        for a in body.answers:
            histories[a.item_id].append(dict(question=allowed[(a.item_id,a.question_id)],answer=a.answer,question_id=a.question_id))
        combined=[a for records in histories.values() for a in records]
        if len(combined)>100:raise AuthError(422,'ANSWER_LIMIT','답변 누적 한도를 넘었습니다. 새 평가표로 검토해 주세요.')
        # 해당 평가표 생성 당시의 기준 스냅샷만 사용한다.
        scenarios=[it['catalog']['scenario'] for it in doc['items']]
        db.rollback()
        reports=catalog_ai.analyze(catalog_ai.restore_input(doc),scenarios,combined,prior)
        current=owned(db,email,no,True);writable(current,body.revision)
        if current['generation_source']!=m['generation_source']:
            raise AuthError(409,'PROVIDER_CHANGED','평가표 생성 기준이 변경됐어요.')
        byid={r['scenario_id']:r for r in reports}
        for it in doc['items']:
            state=it['catalog'];report=byid[state['scenario']['id']]
            remaining={q['id'] for q in report['questions']}
            unanswered={q['id'] for q in state['ai_analysis']['questions'] if (it['id'],q['id']) not in submitted}
            if unanswered-remaining:raise AuthError(502,'AI_QUESTION_DROPPED','답변하지 않은 질문이 누락됐어요. 기존 상태를 유지합니다.')
            state['analysis_history']=(state.get('analysis_history',[])+[state['ai_analysis']])[-10:]
            state['ai_analysis']=report;state['answers']=histories[it['id']]
            # 재분석은 사용자의 현재 조치 확인을 대신하지 않는다.
            edit=ItemEdit(id=it['id'],none=it['none'],keep=it['keep'],owner=it['owner'],due=it['due'] or None,
                          curr=[{k:a[k] for k in ('id','text','checked')} for a in it['curr']],
                          plans=[{k:a[k] for k in ('id','text','checked')} for a in it['plans']],controls_reviewed=False)
            catalog.recalculate(db,it,edit,email,body.revision+1,no)
        execute(db,'UPDATE eval_mst SET revision=revision+1,upt_dt=:t,upt_nm=:e WHERE eval_no=:n',n=no,t=now(),e=email)
        db.commit();return detail(db,email,no)
    except Exception:
        db.rollback();raise
