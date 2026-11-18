"""고정 입력·추출 예제로 새 검색/후처리를 실행한다. 네트워크 호출 없음."""
import argparse
import copy
import json
from .contracts import read, load_catalog
from .pipeline import run_pipeline

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", choices=["unknown", "critical_supported", "all_supported"], default="unknown")
    args = parser.parse_args()
    context = read("examples/" + args.case + "/input.json")
    fixed = read("examples/" + args.case + "/analysis.json")
    def extract(context, batch, catalog):
        ids = {c["scenario_id"] for c in batch["candidates"]}
        return dict(contract_version="assessment-authoring-1",
                    candidates=[copy.deepcopy(c) for c in fixed["candidates"] if c["scenario_id"] in ids],
                    unmatched_risks=[])
    result = run_pipeline(context, build_context=copy.deepcopy, extract_analysis=extract, catalog_snapshot=load_catalog())
    print(json.dumps(result, ensure_ascii=False, indent=2))

if __name__ == "__main__":
    main()

