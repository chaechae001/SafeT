"""DB integration: new → partial save → reload → validate → confirm → locked."""
import copy
import uuid
import pytest
from sqlalchemy import text
from conftest import engine
from test_workplaces import make_login

@pytest.fixture
def flow(client,email,biz_code,monkeypatch):
    monkeypatch.setenv('SAFET_ASSESSMENT_MODE','demo')
    auth=make_login(client,email)
    w=client.post('/workplaces',headers=auth,json={'workplace':'작성흐름 시험','biz_code':biz_code,'custom_machines':['튀김기']}).json()['work_no']
    payload={'request_key':str(uuid.uuid4()),'work_no':w,'eval_dt':'2026-11-16','eval_writer':'작성자','members':['근로자'],'text':'튀김기 앞 바닥에 물기가 있어요.'}
    yield auth,payload
    with engine.begin() as c:
        q='SELECT eval_no FROM eval_mst WHERE email=:e'
        c.execute(text(f'DELETE FROM eval_action WHERE eval_dtl_no IN (SELECT eval_dtl_no FROM eval_dtl WHERE eval_no IN ({q}))'),{'e':email})
        for table in ('eval_file','eval_machine','eval_dtl'):
            c.execute(text(f'DELETE FROM {table} WHERE eval_no IN ({q})'),{'e':email})

def create(client,flow):
    h,p=flow;r=client.post('/evals',headers=h,json=p);assert r.status_code==201,r.text;return r.json()
def edits(doc,complete=False):
    items=[]
    for it in doc['items']:
        out={k:copy.deepcopy(it[k]) for k in ('id','none','keep','owner','due','curr','plans')}
        out['controls_reviewed']=it.get('controls_reviewed',False)
        out['due']=out['due'] or None
        for key in ('curr','plans'):
            out[key]=[{k:a[k] for k in ('id','text','checked')} for a in out[key]]
        if complete:
            out['none']=True
            if it['signal']=='G':out['keep']='Y'
            else:
                out['plans'][0]['checked']=True;out['owner']={'type':'R','name':'근로자'};out['due']='2026-11-20'
        items.append(out)
    return {'revision':doc['revision'],'items':items}

def test_roundtrip_partial_save_confirm_lock(client,flow):
    h,p=flow;doc=create(client,flow);no=doc['eval_no']
    assert doc['generation_source']=='demo' and len(doc['items'])==3
    assert doc['machines'][0]['machine_nm']=='튀김기'
    assert all(not a['checked'] for it in doc['items'] for a in it['curr']+it['plans'])
    saved=client.put(f'/evals/{no}',headers=h,json=edits(doc));assert saved.status_code==200,saved.text
    fresh=client.get(f'/evals/{no}',headers=h).json();assert fresh['revision']==2
    bad=client.post(f'/evals/{no}/confirm',headers=h,json=edits(fresh));assert bad.status_code==422
    assert bad.json()['detail']['errors'][0]['field']=='current'
    assert client.get(f'/evals/{no}',headers=h).json()['revision']==2
    ok=client.post(f'/evals/{no}/confirm',headers=h,json=edits(fresh,True));assert ok.status_code==200,ok.text
    done=ok.json();assert done['eval_status']=='C' and done['confirm_dt']
    assert any(x['eval_no']==no for x in client.get('/evals?tab=C',headers=h).json()['items'])
    assert client.put(f'/evals/{no}',headers=h,json=edits(done)).status_code==409
    assert client.post(f'/evals/{no}/items',headers=h,json={'revision':done['revision'],'keyword':'배달'}).status_code==409
    assert client.post(f'/evals/{no}/confirm',headers=h,json=edits(done,True)).status_code==409

def test_duplicate_create_is_idempotent(client,flow):
    a=create(client,flow);b=create(client,flow);assert a['eval_no']==b['eval_no']

def test_stale_save_does_not_overwrite(client,flow):
    h,_=flow;doc=create(client,flow);p=edits(doc)
    assert client.put(f"/evals/{doc['eval_no']}",headers=h,json=p).status_code==200
    r=client.put(f"/evals/{doc['eval_no']}",headers=h,json=p)
    assert r.status_code==409 and r.json()['detail']['code']=='STALE_REVISION'

def test_invalid_action_rolls_back_all_edits(client,flow):
    h,_=flow;doc=create(client,flow);p=edits(doc,True);p['items'][-1]['curr'][0]['id']=p['items'][0]['curr'][0]['id']
    r=client.put(f"/evals/{doc['eval_no']}",headers=h,json=p);assert r.status_code==400
    after=client.get(f"/evals/{doc['eval_no']}",headers=h).json();assert after['revision']==1 and not after['items'][0]['none']

def test_unknown_blocks_confirmation_without_fake_grade(client,flow,monkeypatch):
    monkeypatch.delenv('SAFET_ASSESSMENT_MODE');h,_=flow;doc=create(client,flow)
    assert doc['generation_source']=='unavailable' and doc['items'][0]['signal']=='N'
    p=edits(doc);p['items'][0]['none']=True
    r=client.post(f"/evals/{doc['eval_no']}/confirm",headers=h,json=p);assert r.status_code==422
    assert any(e['field']=='signal' for e in r.json()['detail']['errors'])

def test_client_cannot_change_grade_or_source(client,flow):
    h,_=flow;doc=create(client,flow);p=edits(doc);p['items'][0]['signal']='G'
    assert client.put(f"/evals/{doc['eval_no']}",headers=h,json=p).status_code==422

def test_green_choice_required(client,flow):
    h,_=flow;doc=create(client,flow);p=edits(doc,True);p['items'][-1]['keep']=None
    r=client.post(f"/evals/{doc['eval_no']}/confirm",headers=h,json=p)
    assert r.status_code==422 and r.json()['detail']['errors'][0]['field']=='plan'

def test_custom_action_and_keyword_persist(client,flow):
    h,_=flow;doc=create(client,flow);p=edits(doc);p['items'][0]['curr'].append({'text':'직접 확인한 조치','checked':True})
    a=client.put(f"/evals/{doc['eval_no']}",headers=h,json=p);assert a.status_code==200
    assert a.json()['items'][0]['curr'][-1]['ai'] is False
    b=client.post(f"/evals/{doc['eval_no']}/items",headers=h,json={'revision':a.json()['revision'],'keyword':'배달 포장'})
    assert b.status_code==200 and len(b.json()['items'])==4

def test_ownership_and_deleted_workplace(client,flow,email):
    h,p=flow;doc=create(client,flow)
    assert client.get(f"/evals/{doc['eval_no']}").status_code==401
    # Own a second actual user so FK integrity is preserved.
    other='other'+uuid.uuid4().hex[:8]+'@test.invalid';oh=make_login(client,other)
    try:
        assert client.get(f"/evals/{doc['eval_no']}",headers=oh).status_code==404
        assert client.put(f"/evals/{doc['eval_no']}",headers=oh,json=edits(doc)).status_code==404
        assert client.post(f"/evals/{doc['eval_no']}/confirm",headers=oh,json=edits(doc,True)).status_code==404
        pp=copy.deepcopy(p);pp['request_key']=str(uuid.uuid4());assert client.post('/evals',headers=oh,json=pp).status_code==404
    finally:
        with engine.begin() as c:c.execute(text('DELETE FROM `user` WHERE email=:e'),{'e':other})
    client.delete(f"/workplaces/{p['work_no']}",headers=h)
    p['request_key']=str(uuid.uuid4());assert client.post('/evals',headers=h,json=p).status_code==404

def test_invalid_date_and_empty_input(client,flow):
    h,p=flow;p['text']='';assert client.post('/evals',headers=h,json=p).status_code==422
    p['text']='관찰';p['eval_dt']='2026-02-30';assert client.post('/evals',headers=h,json=p).status_code==422

def test_photo_preserved_and_svg_rejected(client,flow):
    import base64
    h,p=flow;p['text']='';p['photos']=[{'name':'sample.png','place':'주방','data':'data:image/png;base64,'+base64.b64encode(b'\x89PNG\r\n\x1a\nfixture').decode()}]
    doc=create(client,flow);assert doc['inputs'][0]['file_text']==p['photos'][0]['data']
    p['photos'][0]['data']='data:image/svg+xml;base64,PHN2Zz4=';p['request_key']=str(uuid.uuid4())
    assert client.post('/evals',headers=h,json=p).status_code==422


def test_long_keyword_fits_erd_columns(client,flow):
    h,_=flow;doc=create(client,flow)
    r=client.post(f"/evals/{doc['eval_no']}/items",headers=h,json={'revision':1,'keyword':'가'*200})
    assert r.status_code==200,r.text
    assert len(r.json()['items'][-1]['job'])<=100
