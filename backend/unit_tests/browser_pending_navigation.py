"""실제 초안 화면에서 다음 항목은 담당자의 작업 확인을 대신하지 않는다."""
import threading
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

from browser_workplace_edit_smoke import Quiet


def main():
    frontend = Path(__file__).resolve().parents[2] / 'frontend'
    server = ThreadingHTTPServer(('127.0.0.1', 0), partial(Quiet, directory=str(frontend)))
    threading.Thread(target=server.serve_forever, daemon=True).start()
    origin = f'http://127.0.0.1:{server.server_port}'
    profile = dict(email='fixture@test.invalid', name='검토', has_workplace=True)
    doc = dict(eval_no=1, eval_status='W', eval_nm='검토 평가표', eval_writer='검토', members=[],
               generation_source='demo', revision=1, items=[dict(id=1, job='조리', signal='Y')],
               pending_rows=[dict(scenario_id='FRY', job='튀김', type='화상', title='기름',
                                  machine_kind='unregistered', machine='사진 기기')])
    writes = []
    try:
        with sync_playwright() as pw:
            browser = pw.chromium.launch(channel='msedge')
            page = browser.new_page()
            def api(route):
                if route.request.method != 'GET':
                    writes.append(route.request.url)
                    route.fulfill(status=409, json={})
                else:
                    route.fulfill(json=profile if route.request.url.endswith('/auth/me') else doc)
            page.route('**/api/**', api)
            page.route('https://**/*', lambda route: route.abort())
            page.add_init_script("window.SAFET_API_BASE=location.origin+'/api';")
            page.goto(origin+'/js/config.js')
            page.evaluate("p=>{sessionStorage.setItem('safet.token','fixture');sessionStorage.setItem('safet.user',JSON.stringify(p));}", profile)
            page.goto(origin+'/pages/draft.html?eval=1')
            page.locator('#risk-list a[data-index="0"]').click()
            page.locator('#d-next').click()
            pending = page.locator('#risk-list a[data-pending="FRY"]')
            expect(pending).to_be_visible()
            expect(pending).to_be_focused()
            expect(page.locator('#risk-list a[data-index]')).to_have_count(1)
            assert not writes, writes

            doc['pending_rows'] = []
            doc['items'].append(dict(id=2, job='청소', signal='Y'))
            page.reload()
            page.locator('#risk-list a[data-index="1"]').click()
            page.locator('#d-goto-need').click()
            page.locator('#d-next').click()
            page.locator('#d-next').click()
            expect(page.locator('#d-next')).to_contain_text('검토 마치기')
            page.locator('#d-next').click()
            expect(page.locator('#risk-list')).to_be_visible()
            assert not writes, writes
            browser.close()
    finally:
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()
