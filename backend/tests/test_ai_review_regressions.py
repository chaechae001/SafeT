"""외부 AI 대신 모의 콜백 중 다른 DB 요청을 실행해 경합·보존을 검증한다."""
import copy
from contextlib import contextmanager
import pytest
from sqlalchemy import text
from database import SessionLocal
from conftest import engine
from test_assessment import flow, create, edits
from test_catalog_flow import catalog_flow
from test_catalog_ai_flow import ai_flow
from services import assessment, catalog_ai, trash
from services.auth import AuthError
from schemas.assessment import SaveAssessment


@contextmanager
def short_wait():
    # 풀에 반환되는 연결의 세션 설정을 원복한다.
    with engine.begin() as c:
        original=c.execute(text('SELECT @@innodb_lock_wait_timeout')).scalar_one()
        c.execute(text('SET SESSION innodb_lock_wait_timeout=1'))
        try:
            yield c
        finally:
            c.execute(text('SET SESSION innodb_lock_wait_timeout=:v'),{'v':original})


def owner(no):
    with engine.connect() as c:
        return c.execute(text('SELECT email FROM eval_mst WHERE eval_no=:n'),{'n':no}).scalar_one()


def test_auth_snapshot_conflict_returns_409(client, catalog_flow):
    h,_=catalog_flow;doc=create(client,catalog_flow);no=doc['eval_no'];email=owner(no)
    with SessionLocal() as db:
        db.execute(text('SET SESSION innodb_snapshot_isolation=ON'))
        db.execute(text('SELECT * FROM user WHERE email=:e'),{'e':email}).all()
        r=client.put(f'/evals/{no}',headers=h,json=edits(doc));assert r.status_code==200
        with pytest.raises(AuthError) as err:
            assessment.save(db,email,no,SaveAssessment(**edits(doc)))
        assert err.value.status==409 and err.value.code=='STALE_REVISION'


@pytest.mark.parametrize('operation',['answers','add'])
@pytest.mark.parametrize('change',['save','delete','confirm'])
def test_analysis_rechecks_concurrent_change(client, ai_flow, monkeypatch, operation, change):
    flow,report=ai_flow;h,_=flow;doc=create(client,flow);no=doc['eval_no']
    calls=[]
    def concurrent(*args):
        calls.append(1)
        # 독립 연결에서 1초 이내 잠금을 얻어야 한다. AI가 행을 잠그고 있으면 실패한다.
        with short_wait() as c:
            if change=='save':
                c.execute(text('UPDATE eval_mst SET revision=revision+1, eval_nm=:v WHERE eval_no=:n'),{'v':'동시 수정 보존','n':no})
            elif change=='delete':
                c.execute(text("UPDATE eval_mst SET del_yn='Y' WHERE eval_no=:n"),{'n':no})
            else:
                c.execute(text("UPDATE eval_mst SET eval_status='C', revision=revision+1 WHERE eval_no=:n"),{'n':no})
        out=copy.deepcopy(report);out['candidates'][0]['questions']=[]
        if operation=='add':out['candidates'][0]['scenario_id']='KNIFE_STORAGE'
        return out
    monkeypatch.setattr(catalog_ai,'request_analysis',concurrent)
    body=({'revision':doc['revision'],'answers':[{'item_id':doc['items'][0]['id'],'question_id':'Q1','answer':'실제 사용합니다.'}]}
          if operation=='answers' else {'revision':doc['revision'],'keyword':'칼 보관'})
    r=client.post(f'/evals/{no}/'+('risk-answers' if operation=='answers' else 'items'),headers=h,json=body)
    assert r.status_code==(404 if change=='delete' else 409),r.text
    assert len(calls)==1
    with engine.connect() as c:
        assert c.execute(text('SELECT COUNT(*) FROM eval_dtl WHERE eval_no=:n'),{'n':no}).scalar()==1
    if change!='delete':
        fresh=client.get(f'/evals/{no}',headers=h).json()
        assert fresh['items']==doc['items']
        if change=='save':assert fresh['eval_nm']=='동시 수정 보존'


@pytest.mark.parametrize('change',['update','delete'])
def test_create_rechecks_workplace_after_analysis(client, ai_flow, monkeypatch, change):
    flow,report=ai_flow;h,p=flow
    def concurrent(*args):
        with short_wait() as c:
            sql=("UPDATE workplaces SET workplace='동시 변경' WHERE work_no=:n" if change=='update'
                 else "UPDATE workplaces SET use_yn='N' WHERE work_no=:n")
            c.execute(text(sql),{'n':p['work_no']})
        return copy.deepcopy(report)
    monkeypatch.setattr(catalog_ai,'request_analysis',concurrent)
    r=client.post('/evals',headers=h,json=p)
    assert r.status_code==(409 if change=='update' else 404),r.text
    with engine.connect() as c:
        assert c.execute(text('SELECT COUNT(*) FROM eval_mst WHERE request_key=:k'),{'k':p['request_key']}).scalar()==0


def test_trash_auth_snapshot_does_not_purge_restored_document(client, catalog_flow):
    from datetime import timedelta
    h,_=catalog_flow;doc=create(client,catalog_flow);no=doc['eval_no'];email=owner(no)
    assert client.delete(f'/evals/{no}',headers=h).status_code==204
    with SessionLocal() as db:
        db.execute(text('SET SESSION innodb_snapshot_isolation=ON'))
        db.execute(text('SELECT * FROM user WHERE email=:e'),{'e':email}).all()
        assert client.post(f'/trash/{no}/restore',headers=h).status_code==200
        assert trash._purge_expired(db,email,trash.now()+timedelta(days=31))==0
        db.commit()
    assert client.get(f'/evals/{no}',headers=h).status_code==200


def test_photo_cache_survives_save_reload_and_answers(client, ai_flow, monkeypatch):
    flow,report=ai_flow;h,p=flow
    p['photos']=[{'name':'synthetic.jpg','place':'합성 주방','data':'data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l9sAAAAASUVORK5CYII='}]
    calls=[]
    def detect(photos):
        calls.append(1)
        return {'model':'synthetic-sam','detections':[]}
    monkeypatch.setattr(catalog_ai,'detect_equipment',detect)
    report['candidates'][0]['questions']=[{'id':f'Q{i}','text':f'확인 {i}'} for i in range(1,11)]
    doc=create(client,flow);url=f"/evals/{doc['eval_no']}"
    assert len(doc['items'][0]['catalog']['ai_analysis']['questions'])==11
    doc=client.get(url,headers=h).json()
    report['candidates'][0]['questions']=report['candidates'][0]['questions'][1:]
    r=client.post(url+'/risk-answers',headers=h,json={'revision':doc['revision'],'answers':[
        {'item_id':doc['items'][0]['id'],'question_id':'Q1','answer':'확인했습니다.'}]})
    assert r.status_code==200,r.text
    ids={q['id'] for q in r.json()['items'][0]['catalog']['ai_analysis']['questions']}
    assert ids=={f'Q{i}' for i in range(2,11)}|{'EQUIPMENT_CONFIRM_FRY'}
    assert len(calls)==1
    assert r.json()['items'][0]['signal']=='N'


def test_create_duplicate_during_analysis_returns_same_document(client, ai_flow, monkeypatch):
    flow,report=ai_flow;h,p=flow;created=[]
    original=catalog_ai.request_analysis
    def concurrent(*args):
        monkeypatch.setattr(catalog_ai,'request_analysis',original)
        r=client.post('/evals',headers=h,json=p)
        assert r.status_code==201,r.text
        created.append(r.json()['eval_no'])
        return copy.deepcopy(report)
    monkeypatch.setattr(catalog_ai,'request_analysis',concurrent)
    doc=create(client,flow)
    assert created==[doc['eval_no']]
    with engine.connect() as c:
        assert c.execute(text('SELECT COUNT(*) FROM eval_mst WHERE request_key=:k'),{'k':p['request_key']}).scalar()==1


@pytest.mark.parametrize('code,attempts',[(1020,2),(1205,1),(1213,1)])
def test_lock_conflict_is_bounded_and_returns_409(monkeypatch, code, attempts):
    from sqlalchemy.exc import OperationalError
    calls=[]
    class FakeSession:
        def rollback(self): pass
    def fail(*args,**kwargs):
        calls.append(1)
        raise OperationalError('synthetic lock',{},Exception(code,'synthetic conflict'))
    monkeypatch.setattr(assessment,'rows',fail)
    with pytest.raises(AuthError) as err:
        assessment.owned(FakeSession(),'fixture@test.invalid',1,lock=True)
    assert err.value.code=='CONCURRENT_CHANGE' and err.value.status==409
    assert len(calls)==attempts
