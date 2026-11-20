"""위험·법령 키워드 조회 독립 서버(표준 라이브러리만 사용).

  python -m ai.risk_law_search.server                      # http://127.0.0.1:8020
  python -m ai.risk_law_search.server --host 0.0.0.0 --port 8020 --data docs/chroma

API
  POST /api/analyze                    새 평가표 만들기 형식 {text, voice_text, machines, photos} → 단위별 위험요인 1~3개, 위험요인별 법령 1개
  GET /api/health                      색인 상태·원본 해시
  GET /api/search?q=키워드[&law_docs=1&law_start=02&card_k=8]
  GET /api/card?id=FOOD-01-H1          카드 한 건과 연결 법령
  GET /api/links                       카드–법령 연결 전체(검토용)
"""
import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .engine import Engine

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PAGE = HERE / "static" / "index.html"
MAX_BODY = 20 * 1024 * 1024  # 플랫폼 형식(사진 6장 base64 포함)을 받을 수 있는 크기


def _int(params, key, default, low, high):
    try:
        return max(low, min(high, int(params.get(key, [default])[0])))
    except ValueError:
        return default


def make_handler(engine):
    class Handler(BaseHTTPRequestHandler):
        server_version = "SafeTRiskLaw/1"

        def _send(self, status, body, content_type="application/json; charset=utf-8"):
            data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            url = urlparse(self.path)
            params = parse_qs(url.query)
            try:
                if url.path in ("/", "/index.html"):
                    return self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
                if url.path == "/api/health":
                    return self._send(200, engine.health())
                if url.path == "/api/search":
                    start = params.get("law_start", [None])[0] or None
                    if start and start not in {d["doc_no"] for d in engine.docs}:
                        return self._send(400, dict(error="INVALID_LAW_START", message="법령 문서 번호를 확인해 주세요."))
                    return self._send(200, engine.search(
                        params.get("q", [""])[0], card_k=_int(params, "card_k", 8, 1, 30),
                        law_docs=_int(params, "law_docs", 1, 1, 9), law_k=_int(params, "law_k", 5, 1, 20),
                        law_start=start))
                if url.path == "/api/card":
                    card = engine.card_by_id.get(params.get("id", [""])[0])
                    if not card:
                        return self._send(404, dict(error="CARD_NOT_FOUND", message="카드를 찾지 못했습니다."))
                    return self._send(200, engine.card_view(card))
                if url.path == "/api/links":
                    return self._send(200, engine.export_links())
                return self._send(404, dict(error="NOT_FOUND"))
            except ValueError as e:
                return self._send(400, dict(error="INVALID_QUERY", message=str(e)))
            except Exception:  # 내부 오류 내용은 응답에 싣지 않는다.
                self.log_error("internal error on %s", url.path)
                return self._send(500, dict(error="INTERNAL", message="조회 중 오류가 발생했습니다."))

        def do_POST(self):
            url = urlparse(self.path)
            if url.path != "/api/analyze":
                return self._send(404, dict(error="NOT_FOUND"))
            try:
                length = int(self.headers.get("Content-Length") or 0)
                if length <= 0 or length > MAX_BODY:
                    return self._send(413 if length > MAX_BODY else 400,
                                      dict(error="INVALID_BODY", message="요청 본문을 확인해 주세요(최대 20MB)."))
                body = json.loads(self.rfile.read(length).decode("utf-8"))
                if not isinstance(body, dict):
                    raise ValueError("JSON 객체로 보내 주세요.")
                machines = body.get("machines") or []
                photos = body.get("photos") or []
                if not isinstance(machines, list) or not isinstance(photos, list):
                    raise ValueError("machines와 photos는 배열이어야 합니다.")
                if len(machines) > 100 or len(photos) > 6:
                    raise ValueError("기기는 100개, 사진은 6장 이하입니다.")
                return self._send(200, engine.analyze(str(body.get("text") or ""), str(body.get("voice_text") or ""),
                                                      machines, photos=len(photos)))
            except (ValueError, UnicodeDecodeError) as e:
                msg = "JSON 형식을 확인해 주세요." if isinstance(e, json.JSONDecodeError) else str(e)
                return self._send(400, dict(error="INVALID_INPUT", message=msg))
            except Exception:
                self.log_error("internal error on %s", url.path)
                return self._send(500, dict(error="INTERNAL", message="분석 중 오류가 발생했습니다."))

        def log_message(self, fmt, *args):
            sys.stderr.write("%s %s\n" % (self.log_date_time_string(), fmt % args))

    return Handler


def main():
    cli = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    cli.add_argument("--host", default=os.getenv("RISK_LAW_HOST", "127.0.0.1"))
    cli.add_argument("--port", type=int, default=int(os.getenv("RISK_LAW_PORT", "8020")))
    cli.add_argument("--data", default=os.getenv("RISK_LAW_DATA_DIR", str(ROOT / "docs" / "chroma")),
                     help="법령 HWPX와 risk_card_data.md가 있는 폴더")
    cli.add_argument("--cards", default=os.getenv("RISK_LAW_CARD_FILE"), help="카드 파일 경로(기본: 데이터 폴더의 risk_card_data.md)")
    cli.add_argument("--as-of", default=os.getenv("RISK_LAW_AS_OF"), help="평가일 YYYY-MM-DD(기본: 오늘)")
    cli.add_argument("--mode", choices=("hybrid", "keyword"), default=os.getenv("RISK_LAW_MODE", "hybrid"),
                     help="hybrid: e5 임베딩+키워드(기본), keyword: 키워드만(모델 없음)")
    cli.add_argument("--model", default=os.getenv("RISK_LAW_MODEL"), help="임베딩 모델(기본 intfloat/multilingual-e5-small)")
    cli.add_argument("--index-dir", default=os.getenv("RISK_LAW_INDEX_DIR"), help="Chroma 저장 폴더(기본 ai/risk_law_search/.index)")
    cli.add_argument("--build-index", action="store_true", help="임베딩 색인만 만들고 종료(배포 시 미리 실행)")
    cli.add_argument("--export-links", metavar="PATH", help="카드–법령 연결 전체를 JSON으로 저장하고 종료(새 파일만)")
    cli.add_argument("--law", choices=("c", "a"), default=os.getenv("RISK_LAW_LAW", "c"),
                     help="위험요인 법령: c(기본, KURE 검색 후보 + 위험유형 주제 확인) | a(카드 연결, 모델 없음). "
                          "c에 필요한 인덱스·패키지가 없으면 a로 대체하고 화면에 경고한다")
    cli.add_argument("--build-alt-index", action="store_true", help="C 법령용 KURE 인덱스만 만들고 종료(CPU 수십 분, 처음 한 번)")
    args = cli.parse_args()
    engine = Engine(args.data, card_file=args.cards, as_of=args.as_of, mode=args.mode,
                    model=args.model, index_dir=args.index_dir, log=lambda m: print(m, flush=True))
    if args.build_alt_index:
        from .law_kure import build
        build(engine, log=lambda m: print(m, flush=True))
        return
    if args.law == "c":
        try:
            from .law_kure import KureLawFinder
            engine.alt_law = KureLawFinder(engine)
            engine.law_policy = "topic_kure"
        except (ImportError, OSError, ValueError) as e:  # 인덱스·패키지·모델 없음 → A로 대체
            engine.law_note = (f"법령은 A(카드 연결)로 표시합니다. C를 쓰려면 --build-alt-index로 인덱스를 먼저 만드세요. "
                               f"(원인: {type(e).__name__}: {e})")
            print("경고: " + engine.law_note, flush=True)
    try:
        from .scenario_map import ScenarioLinker
        engine.scenarios = ScenarioLinker()
    except (OSError, ValueError, KeyError) as e:
        print(f"경고: 위험도 시나리오 연결을 불러오지 못했습니다({type(e).__name__}: {e})", flush=True)
    if args.build_index:
        print(json.dumps(engine.health()["model"], ensure_ascii=False))
        return
    if args.export_links:
        with open(args.export_links, "x", encoding="utf-8") as out:
            json.dump(engine.export_links(), out, ensure_ascii=False, indent=1)
        print(f"저장: {args.export_links}")
        return
    h = engine.health()
    print(f"방식 {h['mode']}" + (f" · 모델 {h['model']['model']}" if h["model"] else "") + " · "
          f"색인 완료 {h['build_seconds']}초 · 카드 {h['cards']['cards']}건(검색 {h['searchable_cards']}) · "
          f"법령 {len(h['laws'])}개 · 조각 {h['law_units']}개(시행 중 {h['law_units_in_force']}) · 평가일 {h['as_of']}"
          + f" · 법령 {'C(KURE+주제)' if h['law_policy'] == 'topic_kure' else 'A(카드 연결)'}"
          + (f" · 시나리오 연결 카드 {h['scenarios']['mapped_cards']}(확정 {h['scenarios']['confirmed_cards']})" if h["scenarios"] else ""),
          flush=True)
    print(f"http://{args.host}:{args.port}/", flush=True)
    ThreadingHTTPServer((args.host, args.port), make_handler(engine)).serve_forever()


if __name__ == "__main__":
    main()
