"""작성 복원 중 사업장 API 응답이 늦는 경우. DB 없이 Edge에서 실행한다."""
import re
import threading
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

from browser_workplace_edit_smoke import Quiet


def main():
    root = Path(__file__).resolve().parents[2]
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(Quiet, directory=str(root / 'frontend')))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f'http://127.0.0.1:{server.server_port}'
    profile = {'email': 'restore@test.invalid', 'name': '검토', 'has_workplace': True}
    machine = {'code': None, 'nm': '직접 추가한 기기'}
    draft = {'email': profile['email'], 'work_no': '2', 'work_touched': True,
             'eval_writer': profile['name'], 'eval_dt_auto': True,
             'added': [machine], 'view': '#v-equipment'}
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel='msedge')
            page = browser.new_page()
            page.route('https://**/*', lambda route: route.abort())
            page.add_init_script("window.SAFET_API_BASE=location.origin+'/api';")
            page.goto(origin + '/js/config.js')
            page.evaluate("""([profile, draft]) => {
                sessionStorage.setItem('safet.token','fixture');
                sessionStorage.setItem('safet.user',JSON.stringify(profile));
                sessionStorage.setItem('safet.write.autosave',JSON.stringify({...draft,at:Date.now()}));
            }""", [profile, draft])
            page.route('**/api/auth/me', lambda route: route.fulfill(json=profile))
            # 첫 로딩에서 목록이 실패해도 기존 보관본은 다시 열 수 있어야 한다.
            page.route('**/api/workplaces', lambda route: route.fulfill(status=503, json={}))
            page.goto(origin + '/pages/write.html')
            expect(page.locator('#v-equipment')).to_have_class(re.compile('is-active'))
            page.wait_for_function("JSON.parse(sessionStorage.getItem('safet.write.autosave')).eval_dt !== undefined")
            saved = page.evaluate("JSON.parse(sessionStorage.getItem('safet.write.autosave'))")
            assert saved['work_no'] == '2' and saved['added'] == [machine], saved
            page.unroute('**/api/workplaces')
            page.route('**/api/workplaces', lambda route: route.fulfill(json=[
                {'work_no': 2, 'workplace': '검토 매장', 'biz_nm': '음식점', 'machines': []}]))
            page.reload()
            expect(page.locator('#work_no')).to_have_value('2')
            expect(page.locator('#eq-added-list')).to_contain_text(machine['nm'])
            browser.close()
    finally:
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
