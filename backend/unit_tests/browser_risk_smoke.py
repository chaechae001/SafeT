"""Manual QA runner: isolated *_test MariaDB + Edge + playwright, synthetic model only.

Runs the real API, DB and frontend. No model accuracy claim. Never run on production DB.
"""
import base64,json,os,sys,threading,time,uuid
from copy import deepcopy
from functools import partial
from http.server import SimpleHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'backend'))
if not os.environ.get('DB_NAME','').endswith('_test'):raise SystemExit('Only isolated *_test DB is allowed')
os.environ['FRONTEND_ORIGINS']='http://127.0.0.1:8087'
os.environ['SAFET_ASSESSMENT_MODE']='restaurant_v2'
from sqlalchemy import text
import bcrypt,httpx,uvicorn
from playwright.sync_api import sync_playwright,expect
from database import engine
from main import app
from services import restaurant_risk as risk

fixture=json.loads((ROOT/'contracts/restaurant_risk_v2/examples.json').read_text(encoding='utf-8'))['cases'][2]['expected_output']['analysis']
def synthetic(data,previous=None):
    result=deepcopy(fixture);result['assessment_id']=data['assessment_id'];result['evidence'][0]['media_id']='TEXT'
    if any(m['id'].startswith('ANSWER-') for m in data['media']):
        h=result['hazards'][0];h.update(severity_options=[2],control_options=[3],decision_evidence_complete=True,uncertainty=[])
        h.update(exposure='물기가 남은 통로로 근로자가 이동하고 출입 통제가 없다는 현재 보고',consequence='넘어져 치료가 필요한 염좌·골절',rationale='물기와 통행 노출이 확인됐고 핵심 조치인 오염 제거·통제가 없어 S2·C3, 상으로 판정한다.')
        h['controls'][0].update(state='absent',evidence_ids=['E1']);result['questions']=[]
    return result
risk.request_analysis=synthetic

class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self,*args):pass

def main():
    api=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=8017,log_level='error'))
    static=ThreadingHTTPServer(('127.0.0.1',8087),partial(QuietHandler,directory=str(ROOT/'frontend')))
    threads=[threading.Thread(target=api.run,daemon=True),threading.Thread(target=static.serve_forever,daemon=True)]
    for t in threads:t.start()
    email='browser-'+uuid.uuid4().hex[:8]+'@test.invalid';biz='B'+uuid.uuid4().hex[:8]
    try:
        for _ in range(100):
            if api.started:break
            time.sleep(.05)
        with engine.begin() as c:
            c.execute(text("INSERT INTO `user`(email,pw,name) VALUES(:e,:pw,'브라우저 검증')"),{'e':email,'pw':bcrypt.hashpw(b'password123',bcrypt.gensalt()).decode()})
            c.execute(text("INSERT INTO biz_category(biz_code,biz_nm) VALUES(:b,'검증 음식점')"),{'b':biz})
        client=httpx.Client(base_url='http://127.0.0.1:8017',trust_env=False)
        auth=client.post('/auth/login',json={'email':email,'password':'password123'}).json()
        headers={'Authorization':'Bearer '+auth['access_token']}
        w=client.post('/workplaces',headers=headers,json={'workplace':'통합 검증 음식점','biz_code':biz,'custom_machines':['튀김기']}).json()
        photo='data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l9sAAAAASUVORK5CYII='
        doc=client.post('/evals',headers=headers,json={'request_key':str(uuid.uuid4()),'work_no':w['work_no'],'eval_dt':'2026-11-17','eval_writer':'브라우저 검증','members':[],'text':'통로 바닥에 물기가 있고 직원이 지납니다.','voice_text':'청소 중인지 모르겠어요','photos':[{'name':'synthetic.png','place':'주방','data':photo}]}).json()
        assert doc.get('eval_no'),doc
        errors=[]
        with sync_playwright() as p:
            browser=p.chromium.launch(channel='msedge',headless=True)
            ctx=browser.new_context(viewport={'width':390,'height':844})
            ctx.add_init_script('window.SAFET_API_BASE="http://127.0.0.1:8017";'+
                'sessionStorage.setItem("safet.token",'+json.dumps(auth['access_token'])+');'+
                'sessionStorage.setItem("safet.user",'+json.dumps(json.dumps({'email':email,'name':'브라우저 검증'},ensure_ascii=False))+');'+
                'sessionStorage.setItem("safet.eval",'+json.dumps(str(doc['eval_no']))+');')
            page=ctx.new_page();page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto('http://127.0.0.1:8087/pages/draft.html')
            expect(page.locator('#risk-q-0')).to_be_visible()
            expect(page.locator('#risk-list')).to_contain_text('잠정 판정 · 상')
            page.locator('#risk-q-0').fill('물기가 남아 있고 통행 통제가 없습니다.')
            page.get_by_role('button',name='답변 반영 · 다시 판단').click()
            expect(page.locator('#risk-list')).to_contain_text('판정 · 상')
            expect(page.locator('#risk-q-0')).to_have_count(0)
            page.locator('#risk-list a').first.click()
            expect(page.locator('#risk-evidence-panel')).to_contain_text('판정 근거')
            page.locator('input[data-kind="none"]').check()
            page.locator('#d-save').click()
            expect(page.locator('#risk-evidence-panel')).to_contain_text('재판정 필요')
            page.locator('#d-rejudge').click()
            page.locator('#risk-additional').fill('현재 조치가 없는 상태를 다시 확인했습니다.')
            page.get_by_role('button',name='답변 반영 · 다시 판단').click()
            expect(page.locator('#risk-list')).to_contain_text('판정 · 상')
            page.locator('#risk-list a').first.click()
            page.locator('#d-plan-list input').first.check()
            page.locator('#d-owner-btn').click()
            expect(page.locator('#assign')).to_be_visible()
            page.locator('#assign-people input').first.check()
            page.locator('#due_dt').fill('2026.11.20')
            page.locator('#assign-form button[type="submit"]').click()
            page.locator('#d-save').click()
            page.locator('#d-mode-link').click()
            page.locator('#btn-confirm').click()
            page.locator('#btn-confirm-ok').click()
            page.wait_for_url('**/result.html')
            page.locator('.result-item').first.click()
            expect(page.locator('#v-detail')).to_be_visible()
            expect(page.locator('#v-detail .page')).to_contain_text('판정 근거')
            expect(page.locator('#v-detail .page')).to_contain_text('자료 근거')
            page.screenshot(path=str(ROOT/'docs/risk/browser-risk-mobile.png'),full_page=True)
            page.set_viewport_size({'width':1280,'height':900})
            page.screenshot(path=str(ROOT/'docs/risk/browser-risk-desktop.png'),full_page=True)
            assert not errors,errors
            browser.close()
        assert client.post(f"/evals/{doc['eval_no']}/risk-answers",headers=headers,json={'revision':999,'answers':[]}).status_code==409
        print('PASS: mobile questions -> reassessment -> control invalidation -> reassessment -> plan/owner -> confirm -> readonly evidence; no JS errors. Synthetic model only.')
    finally:
        api.should_exit=True;static.shutdown();static.server_close()
        for t in threads:t.join(timeout=3)
        with engine.begin() as c:
            for table in ('eval_action',):c.execute(text(f'DELETE FROM {table} WHERE eval_dtl_no IN (SELECT eval_dtl_no FROM eval_dtl WHERE eval_no IN (SELECT eval_no FROM eval_mst WHERE email=:e))'),{'e':email})
            for table in ('eval_file','eval_machine','eval_member','eval_dtl','eval_sign'):c.execute(text(f'DELETE FROM {table} WHERE eval_no IN (SELECT eval_no FROM eval_mst WHERE email=:e)'),{'e':email})
            c.execute(text('DELETE FROM eval_mst WHERE email=:e'),{'e':email})
            c.execute(text('DELETE FROM workplace_machine WHERE work_no IN (SELECT work_no FROM workplaces WHERE email=:e)'),{'e':email})
            c.execute(text('DELETE FROM workplaces WHERE email=:e'),{'e':email})
            c.execute(text('DELETE FROM `user` WHERE email=:e'),{'e':email})
            c.execute(text('DELETE FROM biz_category WHERE biz_code=:b'),{'b':biz})
if __name__=='__main__':main()
