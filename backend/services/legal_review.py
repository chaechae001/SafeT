"""법령 검색은 DB 쓰기 전에 실행하며 판정은 평가 항목에 귀속된다."""
import json
import os
from pathlib import Path
import subprocess

from services.auth import AuthError


def attach(items):
    executable = os.getenv("SAFET_LEGAL_PYTHON")
    if not executable or not items:
        return
    questions = []
    for item in items:
        statements = item.get("authoring", {}).get("row", {}).get("evidence", [])
        questions.append(" ".join([item["job"], item["title"], item["cause"],
                                    *(e["statement"] for e in statements)]))
    worker = Path(__file__).resolve().parents[2] / "ai/legal_review/worker.py"
    try:
        result = subprocess.run([executable, "-X", "utf8", str(worker)],
                                input=json.dumps(questions), capture_output=True, encoding="utf8",
                                check=True, timeout=120 + 95 * len(items))
        reviews = json.loads(result.stdout)
        if len(reviews) != len(items):
            raise ValueError()
        for item, review in zip(items, reviews):
            item["legal_review"] = review
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        raise AuthError(503, "LEGAL_REVIEW_UNAVAILABLE", "법령 검색을 완료하지 못했습니다. 다시 시도해 주세요.") from exc
