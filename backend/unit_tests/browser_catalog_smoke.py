"""명시적으로 실행하는 화면 검사. 실제 API·DB·계산 규칙을 사용하며 Cloud·고정 모의 등급은 사용하지 않는다.
준비된 *_test DB에서만 실행한다. Playwright와 Edge가 필요하다.
"""
import base64, os, sys, json, threading, time, uuid
from pathlib import Path
from functools import partial
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'backend'))
if not os.environ.get('DB_NAME','').endswith('_test'):raise SystemExit('Use isolated *_test DB')
AI_FIXTURE='--ai-fixture' in sys.argv
os.environ.update(SAFET_ASSESSMENT_MODE='catalog_ai_v1' if AI_FIXTURE else 'catalog_v1',FRONTEND_ORIGINS='http://127.0.0.1:8090')
import bcrypt,httpx,uvicorn
from sqlalchemy import text
from database import engine
from main import app
from services.catalog_risk import seed
from playwright.sync_api import sync_playwright,expect

class Quiet(SimpleHTTPRequestHandler):
    def log_message(self,*a):pass

def main():
    if AI_FIXTURE:
        from services import catalog_ai
        from services.auth import AuthError
        failures = []
        os.environ.update(SAFET_AI_BASE_URL='https://fixture.invalid/v1',SAFET_AI_MODEL='synthetic-browser-fixture')
        def fixture(media,images,scenarios,previous=None):
            if previous and failures:
                status, code = failures.pop(0)
                raise AuthError(status, code, '시험 오류: 답변을 유지하고 다시 시도해 주세요.')
            return {'candidates':[{'scenario_id':'FRY','rationale':'합성 응답으로 연결 흐름을 검사합니다.',
                'evidence':[{'media_id':'TEXT','statement':'사용자가 튀김 작업을 입력함'}],
                'questions':[] if previous else [{'id':'Q1','text':'실제로 튀김 작업을 하나요?'}]}],'unmatched_risks':[]}
        catalog_ai.request_analysis=fixture
        catalog_ai.detect_equipment=lambda photos:{'model':'synthetic-sam-fixture','detections':[]}

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
        with sync_playwright() as p:
            b=p.chromium.launch(channel='msedge',headless=True)
            ctx=b.new_context(viewport={'width':390,'height':844})
            ctx.add_init_script('window.SAFET_API_BASE="http://127.0.0.1:8020";sessionStorage.setItem("safet.token",'+json.dumps(token)+');sessionStorage.setItem("safet.user",'+json.dumps(json.dumps({'email':email,'name':'검증 작성자'},ensure_ascii=False))+');')
            page=ctx.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
            page.goto('http://127.0.0.1:8090/pages/write.html')
            page.locator('button[form="basic-form"]').click()
            page.locator('#file_text').fill('튀김 조리 작업')
            page.locator('#photo-input').set_input_files({'name':'synthetic.png','mimeType':'image/png','buffer':base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+/l9sAAAAASUVORK5CYII=')})
            page.evaluate("$('#file_text').before('<textarea id=\"voice_text\"></textarea>')")
            page.locator('#voice_text').fill('음성 전사문 입력 경로 검사')
            page.locator('button[form="field-form"]').click()
            page.locator('button[form="equip-form"]').click()
            page.wait_for_url('**/draft.html')
            if AI_FIXTURE:
                expect(page.locator('#ai-question-panel textarea')).to_have_count(2)
                for answer in page.locator('#ai-question-panel textarea').all():
                    answer.fill('튀김기가 있으며 현재 튀김 작업을 합니다.')
                # 실제 API에서 실패를 발생시켜 답변·DB 보존 및 재시도를 검증한다.
                no = page.evaluate('sessionStorage.getItem("safet.eval")')
                before = client.get('/evals/' + str(no), headers=auth).json()
                for status, code in [(503, 'AI_REQUEST_FAILED'), (503, 'AI_TOKENIZE_FAILED'), (422, 'AI_INPUT_TOO_LONG')]:
                    failures.append((status, code))
                    with page.expect_response(lambda r: '/risk-answers' in r.url) as pending:
                        page.get_by_role('button', name='답변 반영', exact=True).click()
                    assert pending.value.status == status
                    expect(page.locator('#safet-loading')).to_be_hidden()
                    expect(page.locator('#safet-toast')).to_contain_text('답변을 유지')
                    for answer in page.locator('#ai-question-panel textarea').all():
                        expect(answer).to_have_value('튀김기가 있으며 현재 튀김 작업을 합니다.')
                    assert client.get('/evals/' + str(no), headers=auth).json() == before
                page.get_by_role('button',name='답변 반영',exact=True).click()
                expect(page.locator('#ai-question-panel')).to_be_hidden(timeout=15000)
            page.locator('#risk-list a').first.click()
            page.locator('[data-kind="none"]').check()
            page.locator('[data-kind="reviewed"]').check()
            page.locator('#d-save').click();page.locator('#safet-confirm [data-answer="yes"]').click()
            expect(page.locator('#d-signal')).to_have_attribute('data-signal','R')
            # 기존 체크박스만으로 현재 위험도를 재계산한다.
            page.locator('#d-curr-list input[data-kind="curr"]').first.check()
            for box in page.locator('#d-curr-list input[data-kind="curr"]').all():box.check()
            page.locator('[data-kind="reviewed"]').check()
            page.locator('#d-save').click();page.locator('#safet-confirm [data-answer="yes"]').click()
            expect(page.locator('#d-signal')).to_have_attribute('data-signal','Y')
            # 현재 조치를 해제한 뒤 계획만 선택해도 현재 위험도가 낮아지지 않는지 확인한다.
            page.locator('[data-kind="none"]').check()
            for box in page.locator('#d-plan-list input').all():box.check()
            page.locator('#d-owner-btn').click();page.locator('#assign-people input').first.check()
            page.locator('#due_dt').fill('2026.12.01');page.locator('#assign-form button[type="submit"]').click()
            page.locator('[data-kind="reviewed"]').check()
            page.locator('#d-save').click();page.locator('#safet-confirm [data-answer="yes"]').click();expect(page.locator('#d-signal')).to_have_attribute('data-signal','R')
            expect(page.locator('#d-projection')).to_contain_text('예상 위험도: 중')
            page.locator('#d-mode-link').click()
            # PR24: 초안을 삭제·복원해도 AI 근거/질문/계산 상태가 그대로 유지된다.
            no = page.evaluate('sessionStorage.getItem("safet.eval")')
            before_trash = client.get('/evals/' + str(no), headers=auth).json()
            page.locator('.draft__delete').click()
            page.locator('#delete .btn--danger').click()
            page.wait_for_url('**/home.html?deleted=1')
            assert client.get('/evals/' + str(no), headers=auth).status_code == 404
            page.goto('http://127.0.0.1:8090/pages/trash.html')
            page.locator('[data-eval="' + str(no) + '"] [data-restore]').click()
            page.wait_for_url('**/home.html')
            assert client.get('/evals/' + str(no), headers=auth).json() == before_trash
            page.goto('http://127.0.0.1:8090/pages/draft.html?eval=' + str(no))
            page.locator('#risk-list a').first.click()
            expect(page.locator('#d-signal')).to_have_attribute('data-signal','R')
            expect(page.locator('#d-projection')).to_contain_text('예상 위험도: 중')
            (ROOT/'.venv').mkdir(exist_ok=True)
            page.screenshot(path=str(ROOT/('.venv/ai-risk-preview.png' if AI_FIXTURE else '.venv/agreed-risk-preview.png')),full_page=True)
            page.locator('#d-mode-link').click();page.locator('#btn-confirm').click();page.locator('#btn-confirm-ok').click()
            page.wait_for_url('**/result.html')
            expect(page.get_by_role('link',name='개선대책 이행 관리')).to_have_count(0)
            page.locator('.result-item').first.click()
            expect(page.locator('#v-detail')).to_contain_text('개선 후 예상 신호')
            expect(page.locator('#v-detail')).to_contain_text('계획 단계의 예상')
            no=page.evaluate('sessionStorage.getItem("safet.eval")')
            doc=client.get('/evals/'+no,headers=auth).json()
            assert doc['items'][0]['signal']=='R' and doc['items'][0]['after']=='Y'
            if AI_FIXTURE:
                assert doc['generation_source']=='catalog_ai_v1'
                expect(page.locator('#v-detail')).to_contain_text('AI가 찾은 위험 후보와 근거')
            page.reload();expect(page.locator('.result-item')).to_have_count(1)
            # 확정 자료 삭제 차단 및 별도 합성 초안 영구 삭제 UI 검사.
            assert client.delete('/evals/' + str(no), headers=auth).status_code == 409
            extra = client.post('/evals', headers=auth, json={
                'request_key': str(uuid.uuid4()), 'work_no': doc['work_no'],
                'eval_dt': '2026-11-18', 'eval_writer': '검증 작성자', 'members': ['검증 작성자'],
                'text': '합성 튀김 작업', 'catalog_ids': ['FRY']})
            extra.raise_for_status()
            extra_no = extra.json()['eval_no']
            assert client.delete('/evals/' + str(extra_no), headers=auth).status_code == 204
            page.goto('http://127.0.0.1:8090/pages/trash.html')
            card = page.locator('[data-eval="' + str(extra_no) + '"]')
            card.locator('[data-purge]').click()
            page.locator('#purge-ok').click()
            expect(card).to_have_count(0)
            assert client.post('/trash/' + str(extra_no) + '/restore', headers=auth).status_code == 404
            assert not errors,errors
            b.close()
        print('PASS: AI failure/retry preserves answers and DB (AI fixture mode); existing input -> current R/Y -> planned projection Y with current R -> trash/restore preserves document -> confirm -> readonly/reload -> permanent deletion; no appendix views, no Cloud, no JS errors')
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
