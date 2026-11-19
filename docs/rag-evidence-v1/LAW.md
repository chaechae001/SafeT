# 법령 원문 분리

Python 3.9 이상에서 이 폴더를 기준으로 실행한다. 출력 위치는 저장소 밖의 새 파일로 지정한다.

```powershell
$root = 'D:\SafeT-data'
python -X utf8 parse_law_hwpx.py "$root\법령" "$root\본문조문_v1.jsonl"
```

한 줄이 본문 조문 한 건이다. 파일명·해시·시행본·조문 번호·제목·문단을 보존한다. 삭제 조문은 deleted로 표시한다. 부칙은 첫 부칙 표제에서 분리해 출력 대상에서 제외하며, 표는 table_review_required로 표시한다. 별도 시행일·부칙·별표·표 안의 내용은 추가 대조한 뒤 검색에 사용한다. 출력은 Chroma 적재 전 검토 자료다.
