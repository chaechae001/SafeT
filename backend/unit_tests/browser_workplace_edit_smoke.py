"""사업장 수정 입력 보존 회귀 검사. DB·실제 AI·외부 서버 호출 없음.
저장소 루트에서 Python + Playwright + Edge 환경으로 실행:
python backend/unit_tests/browser_workplace_edit_smoke.py
"""
import json
import threading
from functools import partial
from http.server import ThreadingHTTPServer, SimpleHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[2]

class Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *args):
        pass

def main():
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(Quiet, directory=str(ROOT / 'frontend')))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    profile = {'email': 'fixture@test.invalid', 'name': '검수 사용자', 'has_workplace': True}
    workplace = {'work_no': 1, 'workplace': '기존 사업장', 'biz_code': 'FIXTURE', 'biz_nm': '검수 업종',
                 'machines': [{'machine_code': None, 'machine_nm': '튀김기', 'custom': True}], 'draft_count': 0}
    state = {'loading_checked': False, 'saves': 0}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel='msedge', headless=True)
            context = browser.new_context()
            context.add_init_script('window.SAFET_API_BASE="http://127.0.0.1:8022";'
                                    'sessionStorage.setItem("safet.token","fixture");'
                                    'sessionStorage.setItem("safet.user",' + json.dumps(json.dumps(profile)) + ');')
            page = context.new_page()
            def api(route):
                path = urlparse(route.request.url).path
                status = 200
                if path == '/auth/me':
                    data = profile
                elif path == '/workplaces':
                    data = [workplace]
                elif path == '/biz-categories':
                    data = [{'biz_code': 'FIXTURE', 'biz_nm': '검수 업종'}]
                elif path.endswith('/machines'):
                    data = []
                elif path == '/workplaces/1' and route.request.method == 'GET':
                    # 응답을 보내기 전, 입력이 불가능해야 늦은 응답에 수정 내용이 사라지지 않습니다.
                    expect(page.locator('#edit-workplace')).to_be_disabled()
                    expect(page.locator('#edit-machine-add')).to_be_disabled()
                    state['loading_checked'] = True
                    data = workplace
                elif path == '/workplaces/1' and route.request.method == 'PUT':
                    state['saves'] += 1
                    if state['saves'] == 1:
                        status = 503
                        data = {'detail': {'code': 'TEST_ERROR', 'message': '검수용 저장 오류'}}
                    else:
                        body = route.request.post_data_json
                        assert body['workplace'] == '수정한 사업장'
                        assert body['custom_machines'] == ['튀김기', '작업대']
                        workplace['workplace'] = body['workplace']
                        data = {'work_no': 1}
                else:
                    raise AssertionError('Unexpected local API request: ' + path)
                route.fulfill(status=status, content_type='application/json', body=json.dumps(data))
            context.route('http://127.0.0.1:8022/**', api)
            page.goto(f'http://127.0.0.1:{server.server_port}/pages/workplace.html')
            page.locator('[data-edit="1"]').click()
            page.locator('#edit-workplace').fill('수정한 사업장')
            page.locator('#edit-machine-add').fill('작업대')
            page.locator('#edit-machine-add-btn').click()
            page.locator('button[form=edit-form]').click()
            expect(page.locator('#safet-toast')).to_contain_text('검수용 저장 오류')
            expect(page.locator('#edit-workplace')).to_have_value('수정한 사업장')
            expect(page.locator('#v-edit input[data-custom]:checked')).to_have_count(2)
            page.locator('button[form=edit-form]').click()
            expect(page.locator('#wp-list')).to_contain_text('수정한 사업장')
            assert state == {'loading_checked': True, 'saves': 2}
            browser.close()
        print('WORKPLACE_EDIT_INPUT_RECOVERY_PASS')
    finally:
        server.shutdown()
        server.server_close()

if __name__ == '__main__':
    main()
