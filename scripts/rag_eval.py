"""基于人工标注 JSONL 的真实检索评测。结果写入忽略的 data/ 目录。

每个案例包含 query、knowledge_base_ids 或 agent_id、
relevant_document_ids；可选 profile_id、min_score、top_k。
relevant_document_ids 为空列表表示无答案案例，不参与正样本召回均值。
本脚本会调用真实 Embedding 服务，先使用少量样本确认成本。
"""

import argparse
import json
import math
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from time import perf_counter
from uuid import UUID

import httpx

from rag_smoke import SmokeError, call, login


def metrics(expected: set[str], retrieved: list[str], k: int) -> dict:
    """文档级评测：同一文档多个片段只算一次，防止重复片段虚增分数。"""

    ranked = list(dict.fromkeys(retrieved))
    if not expected:
        return {"no_evidence": not ranked}
    relevance = [int(doc in expected) for doc in ranked]
    dcg = sum(value / math.log2(index + 2) for index, value in enumerate(relevance))
    ideal = sum(1 / math.log2(index + 2) for index in range(min(k, len(expected))))
    return {
        "recall": len(expected.intersection(ranked)) / len(expected),
        "reciprocal_rank": next(
            (1 / (index + 1) for index, value in enumerate(relevance) if value), 0
        ),
        "ndcg": dcg / ideal if ideal else 0,
    }


def load_cases(path: Path) -> list[dict]:
    cases = []
    seen = set()
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            case = json.loads(line)
            identifier = str(case.get("id", number))
            if identifier in seen:
                raise ValueError("重复案例 ID")
            seen.add(identifier)
            if not isinstance(case["query"], str) or not case["query"].strip():
                raise ValueError("query 必须是非空字符串")
            expected = case["relevant_document_ids"]
            if not isinstance(expected, list):
                raise ValueError("relevant_document_ids 必须是列表")
            for document in expected:
                UUID(document)
            if not case.get("agent_id") and not case.get("knowledge_base_ids"):
                raise ValueError("必须指定查询范围")
            cases.append({**case, "id": identifier})
        except (ValueError, TypeError, KeyError) as error:
            raise ValueError(f"第 {number} 行案例无效：{error}") from error
    if not cases:
        raise ValueError("评测集为空")
    return cases


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--output", type=Path, default=Path("data/evaluations/latest.json"))
    parser.add_argument("--top-k", type=int, default=5, choices=range(1, 21))
    args = parser.parse_args()
    cases = load_cases(args.dataset)
    print(f"将执行 {len(cases)} 次真实检索；空召回与调用失败会分别统计。")
    records = []
    with httpx.Client(base_url=args.base_url, timeout=180) as client:
        login(client)
        for case in cases:
            payload = {
                key: value for key, value in case.items()
                if key in {"query", "agent_id", "knowledge_base_ids", "profile_id", "min_score"}
            }
            payload["top_k"] = args.top_k
            started = perf_counter()
            record = {"id": case["id"]}
            try:
                response = call(client, "POST", "/api/knowledge/search", json=payload)
                documents = [hit["document_id"] for hit in response["hits"]]
                record.update(
                    status="ok", request_id=response["request_id"],
                    retrieved_document_ids=documents,
                    metrics=metrics(set(case["relevant_document_ids"]), documents, args.top_k),
                )
            except (SmokeError, httpx.RequestError) as error:
                # 失败样本不当作无答案成功；正样本按 0 分计入整体结果。
                record.update(status="failed", error=str(error))
                if case["relevant_document_ids"]:
                    record["metrics"] = {"recall": 0, "reciprocal_rank": 0, "ndcg": 0}
            record["latency_ms"] = round((perf_counter() - started) * 1000)
            records.append(record)
            print(f"{record['id']}: {record['status']}")
    positives = [item["metrics"] for item in records if "recall" in item.get("metrics", {})]
    negatives = [item for item, case in zip(records, cases, strict=True) if not case["relevant_document_ids"]]
    timings = sorted(item["latency_ms"] for item in records)
    report = {
        "created_at": datetime.now(UTC).isoformat(),
        "dataset": str(args.dataset), "top_k": args.top_k,
        "summary": {
            "cases": len(records),
            "failures": sum(item["status"] != "ok" for item in records),
            "recall_at_k": mean(item["recall"] for item in positives) if positives else None,
            "mrr": mean(item["reciprocal_rank"] for item in positives) if positives else None,
            "ndcg_at_k": mean(item["ndcg"] for item in positives) if positives else None,
            "negative_empty_rate": (
                sum(item.get("metrics", {}).get("no_evidence", False) for item in negatives)
                / len(negatives) if negatives else None
            ),
            "p50_ms": timings[math.ceil(len(timings) * .5) - 1],
            "p95_ms": timings[math.ceil(len(timings) * .95) - 1],
        },
        # 不把原始问题或证据全文写入报告，标注原文由数据集管理。
        "records": records,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))
    print(f"报告：{args.output.resolve()}")
    if report["summary"]["failures"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
