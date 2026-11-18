"""AI 통합 화면 검사의 호환 실행 진입점."""
import sys
from browser_catalog_smoke import main
import browser_catalog_smoke as smoke
smoke.AI_FIXTURE = True
smoke.os.environ["SAFET_ASSESSMENT_MODE"] = "catalog_ai_v1"
if __name__ == "__main__": main()
