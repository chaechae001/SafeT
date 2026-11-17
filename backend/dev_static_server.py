"""개발용 화면 서버: python -m http.server 와 같지만 브라우저 캐시를 끕니다.

python -m http.server 는 캐시 금지 헤더를 보내지 않아, 브라우저가 고친 JS·CSS 대신
예전 파일을 그대로 쓰는 일이 생깁니다(2026-11-17 sign.js 옛 버전 실행 문제).
개발 확인 전용입니다. 운영 배포에는 쓰지 않습니다.

사용: python backend/dev_static_server.py 8000 --bind 127.0.0.1 --directory frontend
"""
import argparse
import functools
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
        return super().send_head()


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
