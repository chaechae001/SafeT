"""합성 모델 응답으로 기존 화면의 질문·실패 복구·DB 계산·확정·조회를 검사한다. Cloud 정확도 검사가 아니다.
준비된 *_test DB에서만 실행한다. Playwright와 Edge가 필요하다.
"""
import base64, os, sys, json, threading, time, uuid
from pathlib import Path
from functools import partial
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'backend'))
if not os.environ.get('DB_NAME','').endswith('_test'):raise SystemExit('Use isolated *_test DB')
os.environ.update(SAFET_ASSESSMENT_MODE='catalog_ai_v1',FRONTEND_ORIGINS='http://127.0.0.1:8090')
import bcrypt,httpx,uvicorn
from sqlalchemy import text
from database import engine
from main import app
from services.catalog_risk import seed
from services import catalog_ai as ai
from services.auth import AuthError
FAIL=False

def synthetic(input_data,candidates,previous=None):
    if FAIL:raise AuthError(503,'RISK_MODEL_FAILED','합성 모델 오류 · 입력 유지')
    s=next(s for s in candidates if s['id']=='FRY')
    answered=any(m['id'].startswith('ANSWER-') for m in input_data['media'])
    source=next(m for m in input_data['media'] if m['id']=='TEXT')
    return dict(evidence=[dict(id='E1',media_id='TEXT',kind='reported',time_scope='current',statement=source['content'])],
        matches=[dict(scenario_id='FRY',applicability='confirmed',evidence_ids=['E1'],uncertainties=[],
            controls=[dict(control_id=c['id'],state='absent' if answered else 'unknown',evidence_ids=['E1'] if answered else []) for c in s['controls']])],unmatched_observations=[])
ai.request_analysis=synthetic
from playwright.sync_api import sync_playwright,expect

class Quiet(SimpleHTTPRequestHandler):
    def log_message(self,*a):pass

def main():
    global FAIL
    print("Starting isolated browser check",flush=True)
    api=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=8020,log_level='error'))
    static=ThreadingHTTPServer(('127.0.0.1',8090),partial(Quiet,directory=str(ROOT/'frontend')))
    for f in (api.run,static.serve_forever):threading.Thread(target=f,daemon=True).start()
    email='catalog-'+uuid.uuid4().hex[:8]+'@test.invalid';biz='C'+uuid.uuid4().hex[:8]
    try:
        for _ in range(100):
            if api.started:break
            time.sleep(.05)
        with engine.begin() as c:
            seed(c)
            c.execute(text("INSERT INTO `user`(email,pw,name) VALUES(:e,:p,'검증 작성자')"),{'e':email,'p':bcrypt.hashpw(b'password123',bcrypt.gensalt()).decode()})
            c.execute(text("INSERT INTO biz_category(biz_code,biz_nm) VALUES(:b,'검증 음식점')"),{'b':biz})
        client=httpx.Client(base_url='http://127.0.0.1:8020',trust_env=False)
        token=client.post('/auth/login',json={'email':email,'password':'password123'}).json()['access_token']
        auth={'Authorization':'Bearer '+token}
        client.post('/workplaces',headers=auth,json={'workplace':'DB 기준 검증','biz_code':biz,'custom_machines':['튀김기']}).raise_for_status()
        print("API ready, starting browser",flush=True)
        with sync_playwright() as p:
            b=p.chromium.launch(channel='msedge',headless=True)
            ctx=b.new_context(viewport={'width':390,'height':844})
            ctx.add_init_script('window.SAFET_API_BASE="http://127.0.0.1:8020";sessionStorage.setItem("safet.token",'+json.dumps(token)+');sessionStorage.setItem("safet.user",'+json.dumps(json.dumps({'email':email,'name':'검증 작성자'},ensure_ascii=False))+');')
            page=ctx.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            print('Browser ready',flush=True)
            page.goto('http://127.0.0.1:8090/pages/write.html')
            page.locator('button[form="basic-form"]').click()
            page.locator('#file_text').fill('튀김 조리 작업')
            page.locator('#photo-input').set_input_files({'name':'synthetic.png','mimeType':'image/png','buffer':base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l9sAAAAASUVORK5CYII=')})
            page.evaluate("$('#file_text').before('<textarea id=\"voice_text\"></textarea>')")
            page.locator('#voice_text').fill('음성 전사문 입력 경로 검사')
            page.locator('button[form="field-form"]').click()
            page.locator('button[form="equip-form"]').click()
            page.wait_for_url('**/draft.html')
            expect(page.locator('#risk-question-panel')).to_be_visible()
            # 직접 현재 조치를 확인해 질문을 해소하면 숨은 답변 초안이 확정을 막지 않아야 한다.
            page.locator('#risk-question-panel textarea[id^="risk-q-"]').first.fill('답변 작성 중')
            page.locator('#risk-list a').first.click()
            expect(page.locator('#d-curr-list input[data-kind="curr"]')).to_have_count(8)
            for box in page.locator('#d-curr-list input[data-kind="curr"]').all():box.check()
            with page.expect_response(lambda r:r.request.method=='PUT' and '/evals/' in r.url) as saved:
                page.locator('#d-save').click()
            assert saved.value.status==200
            result=saved.value.json()['items'][0]
            assert result['signal']=='Y' and sum(a['checked'] for a in result['curr'])==8 and not result['catalog']['ai']['unknown_ids']
            expect(page.locator('#d-signal')).to_have_attribute('data-signal','Y')
            assert not page.evaluate('SafeT.hasUnsaved()')
            page.locator('#d-mode-link').click()
            page.locator('#risk-additional').fill('현재 상태 재확인')
            page.get_by_role('button',name='답변 반영 · 다시 확인').click()
            expect(page.locator('#risk-question-panel textarea[id^="risk-q-"]')).to_have_count(8)
            # 과거 선택이 남아 있어도 새 미확인 응답은 판단 필요다.
            page.locator('#risk-list a').first.click()
            expect(page.locator('#d-signal')).to_have_attribute('data-signal','N')
            page.locator('#d-mode-link').click()
            if page.locator('#risk-question-panel details summary').count():page.locator('#risk-question-panel details summary').click()
            for field in page.locator('#risk-question-panel textarea[id^="risk-q-"]').all():field.fill('현장에서 없음 확인')
            FAIL=True
            with page.expect_response(lambda r:'/risk-answers' in r.url) as failed:
                page.get_by_role('button',name='답변 반영 · 다시 확인').click()
            assert failed.value.status==503
            expect(page.locator('#risk-question-panel textarea[id^="risk-q-"]').first).to_have_value('현장에서 없음 확인')
            FAIL=False
            page.get_by_role('button',name='답변 반영 · 다시 확인').click()
            expect(page.locator('#risk-question-panel textarea[id^="risk-q-"]')).to_have_count(8)
            expect(page.locator('#risk-question-panel')).to_contain_text('기존 선택과 새 근거가 달라요.')
            page.locator('#risk-list a').first.click()
            page.locator('[data-kind="none"]').check()
            page.locator('#d-save').click()
            expect(page.locator('#d-signal')).to_have_attribute('data-signal','R')
            # 기존 체크박스만으로 현재 위험도를 재계산한다.
            page.locator('#d-curr-list input[data-kind="curr"]').first.check()
            for box in page.locator('#d-curr-list input[data-kind="curr"]').all():box.check()
            page.locator('#d-save').click()
            expect(page.locator('#d-signal')).to_have_attribute('data-signal','Y')
            # 현재 조치를 해제한 뒤 계획만 선택해도 현재 위험도가 낮아지지 않는지 확인한다.
            page.locator('[data-kind="none"]').check()
            for box in page.locator('#d-plan-list input').all():box.check()
            page.locator('#d-owner-btn').click();page.locator('#assign-people input').first.check()
            page.locator('#due_dt').fill('2026.12.01');page.locator('#assign-form button[type="submit"]').click()
            page.locator('#d-save').click();expect(page.locator('#d-signal')).to_have_attribute('data-signal','R')
            page.locator('#d-mode-link').click();page.locator('#btn-confirm').click();page.locator('#btn-confirm-ok').click()
            page.wait_for_url('**/result.html')
            expect(page.get_by_role('link',name='개선대책 이행 관리')).to_have_count(0)
            page.locator('.result-item').first.click()
            expect(page.locator('#v-detail')).to_contain_text('개선 후 예상 신호')
            expect(page.locator('#v-detail')).to_contain_text('계획 단계의 예상')
            expect(page.locator('#v-detail')).to_contain_text('위험요인과 입력 근거')
            no=page.evaluate('sessionStorage.getItem("safet.eval")')
            doc=client.get('/evals/'+no,headers=auth).json()
            assert doc['items'][0]['signal']=='R' and doc['items'][0]['after']=='Y'
            page.reload();expect(page.locator('.result-item')).to_have_count(1)
            assert not errors,errors
            b.close()
        print('PASS: synthetic unknown -> explicit current choices/draft cleanup -> newer unknown N -> model failure/input retained -> conflicting answers N -> explicit correction R -> common current Y -> plan projection Y/current R -> confirm -> readonly evidence/reload; no Cloud, no JS errors')
    finally:
        api.should_exit=True;static.shutdown();static.server_close()
        with engine.begin() as c:
            c.execute(text('DELETE FROM risk_event WHERE actor=:e'),{'e':email})
            q='SELECT eval_no FROM eval_mst WHERE email=:e'
            c.execute(text(f'DELETE FROM eval_action WHERE eval_dtl_no IN (SELECT eval_dtl_no FROM eval_dtl WHERE eval_no IN ({q}))'),{'e':email})
            for table in ('eval_file','eval_machine','eval_member','eval_dtl','eval_sign'):c.execute(text(f'DELETE FROM {table} WHERE eval_no IN ({q})'),{'e':email})
            c.execute(text('DELETE FROM eval_mst WHERE email=:e'),{'e':email})
            c.execute(text('DELETE FROM workplace_machine WHERE work_no IN (SELECT work_no FROM workplaces WHERE email=:e)'),{'e':email})
            c.execute(text('DELETE FROM workplaces WHERE email=:e'),{'e':email})
            c.execute(text('DELETE FROM `user` WHERE email=:e'),{'e':email})
            c.execute(text('DELETE FROM biz_category WHERE biz_code=:b'),{'b':biz})
if __name__=='__main__':main()
