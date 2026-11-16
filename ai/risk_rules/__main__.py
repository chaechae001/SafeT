"""Run from repository root: python -m ai.risk_rules --check"""
import argparse
import json
from pathlib import Path
from .engine import evaluate_case


def main():
    parser = argparse.ArgumentParser(description='Safe-T 3단계 현재/개선 후 예상 등급 실험')
    parser.add_argument('--cases', type=Path, default=Path(__file__).with_name('examples.json'))
    parser.add_argument('--case-id')
    parser.add_argument('--check', action='store_true', help='합성 사례의 기대값과 규칙 회귀검사')
    parser.add_argument('--json', action='store_true', help='상세 JSON을 표준출력으로 출력')
    args = parser.parse_args()
    try:
        cases = json.loads(args.cases.read_text(encoding='utf-8'))
        if not isinstance(cases, list) or not cases:
            raise ValueError('사례 파일은 비어 있지 않은 배열이어야 합니다.')
        ids = [c.get('case_id') for c in cases if isinstance(c, dict)]
        if len(ids) != len(cases) or any(not isinstance(x, str) or not x for x in ids) or len(set(ids)) != len(ids):
            raise ValueError('사례 ID가 누락되었거나 중복됩니다.')
        selected = [c for c in cases if not args.case_id or c['case_id'] == args.case_id]
        if not selected: raise ValueError('해당 사례 ID가 없습니다.')
        results = []; failures = []
        for case in selected:
            result = evaluate_case(case); results.append(result)
            if args.check:
                expected = case.get('expected')
                actual = {'current': result['current']['grade'], 'projected': result['projected']['grade']}
                if expected != actual: failures.append({'case_id': case['case_id'], 'expected': expected, 'actual': actual})
        if args.json:
            print(json.dumps({'results': results, 'check_failures': failures}, ensure_ascii=False, indent=2))
        else:
            print('실험용 후보 / 개선 후는 미실행 가정 / 최종 판단은 현장 검토 필요')
            for r in results:
                print(f"{r['case_id']}: {r['task']} | 현재 {r['current']['label']}({r['current']['grade']}) → 예상 {r['projected']['label']}({r['projected']['grade']})")
            if args.check: print(f'합성 규칙 일치: {len(selected)-len(failures)}/{len(selected)} (현장 정확도 아님)')
            for failure in failures: print(json.dumps(failure, ensure_ascii=False))
        return 1 if failures else 0
    except (ValueError, TypeError, KeyError, OSError) as exc:
        parser.error(str(exc))


if __name__ == '__main__':
    raise SystemExit(main())
