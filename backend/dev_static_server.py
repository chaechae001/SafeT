"""개발용 화면 서버: python -m http.server 와 같지만 브라우저 캐시를 끕니다.

python -m http.server 는 캐시 금지 헤더를 보내지 않아, 브라우저가 고친 JS·CSS 대신
예전 파일을 그대로 쓰는 일이 생깁니다(2026-11-17 sign.js 옛 버전 실행 문제).
개발 확인 전용입니다. 운영 배포에는 쓰지 않습니다.

사용: python backend/dev_static_server.py 8000 --bind 127.0.0.1 --directory frontend
"""
import argparse
import functools
import os
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer


class NoCacheHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header('Cache-Control', 'no-store, must-revalidate')
        self.send_header('Pragma', 'no-cache')
        self.send_header('Expires', '0')
        super().end_headers()

    def send_head(self):
        # If-Modified-Since 로 304 를 돌려주지 않고 항상 새 파일을 보냄
        del self.headers['If-Modified-Since']
        # UX-001: 루트(/)는 폴더 목록 대신 첫 화면으로
        if self.path.split('?', 1)[0] in ('', '/'):
            self.send_response(302)
            self.send_header('Location', 'pages/login.html')   # 상대 주소: /proxy/8022/ 같은 하위 경로에서도 동작
            self.send_header('Content-Length', '0')
            self.end_headers()
            return None
        return super().send_head()

    # UX-001: 폴더 목록을 보여 주지 않고 오류 페이지(404)
    def list_directory(self, path):
        self.send_error(404)
        return None

    # UX-001: 화면 서버가 받지 않는 요청 방식은 405
    def _method_not_allowed(self):
        self.send_error(405)

    do_POST = do_PUT = do_PATCH = do_DELETE = _method_not_allowed

    def send_error(self, code, message=None, explain=None):
        """UX-001: 4xx·5xx 는 기본 문구 대신 frontend/pages/error.html 을 같은 상태 코드로 보냄."""
        page = os.path.join(self.directory, 'pages', 'error.html')
        if code < 400 or not os.path.isfile(page):
            return super().send_error(code, message, explain)
        try:
            with open(page, 'rb') as f:
                body = f.read().replace(b'data-status=""', b'data-status="%d"' % code, 1)
            # 요청 주소 깊이에 맞춘 <base>: /pages/x.html → ../, /a/b/c → ../../ (하위 경로 프록시에서도 화면 루트를 가리킴)
            depth = max(len(self.path.split('?', 1)[0].split('#', 1)[0].split('/')) - 2, 0)
            body = body.replace(b'<base href="../">', b'<base href="%s">' % (b'../' * depth or b'./'), 1)
        except OSError:
            return super().send_error(code, message, explain)
        self.send_response(code, message)
        self.send_header('Content-Type', 'text/html; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        if code == 405:
            self.send_header('Allow', 'GET, HEAD')
        self.end_headers()
        if self.command != 'HEAD':
            self.wfile.write(body)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('port', type=int, nargs='?', default=8000)
    p.add_argument('--bind', default='127.0.0.1')
    p.add_argument('--directory', default='.')
    a = p.parse_args()
    handler = functools.partial(NoCacheHandler, directory=a.directory)
    with ThreadingHTTPServer((a.bind, a.port), handler) as httpd:
        print(f'Serving {a.directory} on http://{a.bind}:{a.port} (no-cache)', flush=True)
        httpd.serve_forever()


if __name__ == '__main__':
    main()
