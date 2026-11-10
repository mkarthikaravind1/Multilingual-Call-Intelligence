"""CLI for LLM evaluation: python -m evalkit.llm --base-url <url> --model <name> --data <file.jsonl>"""

import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional

from evalkit.llm.client import LLMClient, MockLLMClient
from evalkit.llm.scorers import SCORER_REGISTRY, TaskScoreResult


def parse_args():
    parser = argparse.ArgumentParser(description="LLM Evaluation Kit (evalkit.llm)")
    parser.add_argument("--base-url", type=str, default="http://localhost:8000/v1", help="Base URL of OpenAI-compatible API")
    parser.add_argument("--model", type=str, default="local-model", help="Model name")
    parser.add_argument("--data", type=str, required=True, help="Path to evaluation JSONL file")
    parser.add_argument("--api-key-env", type=str, default="OPENAI_API_KEY", help="Env var holding API key")
    parser.add_argument("--mock", action="store_true", help="Run with mock client for offline testing")
    parser.add_argument("--compare-base-url", type=str, default=None, help="Base URL of comparison (e.g. paid) model")
    parser.add_argument("--compare-model", type=str, default=None, help="Model name of comparison model")
    parser.add_argument("--output", type=str, default=None, help="Path to save JSON evaluation report")
    return parser.parse_args()


def evaluate_dataset(client: Any, dataset_path: str) -> List[Dict[str, Any]]:
    results = []
    with open(dataset_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            item = json.loads(line)
            task_name = item["task"]
            prompt = item["prompt"]
            expected = item["expected"]
            scorer = SCORER_REGISTRY.get(task_name)
            if not scorer:
                continue

            comp_resp = client.complete(prompt)
            score_res: TaskScoreResult = scorer.score(comp_resp["content"], expected)

            results.append({
                "id": item.get("id"),
                "task": task_name,
                "prompt": prompt,
                "expected": expected,
                "raw_output": comp_resp["content"],
                "prediction": score_res.prediction,
                "is_valid_json": score_res.is_valid_json,
                "metrics": score_res.metrics,
                "latency_sec": comp_resp["latency_sec"],
                "tokens_per_sec": comp_resp["tokens_per_sec"],
            })
    return results


def summarize_evaluation(results: List[Dict[str, Any]]) -> Dict[str, Any]:
    total_calls = len(results)
    if total_calls == 0:
        return {}

    valid_json_count = sum(1 for r in results if r["is_valid_json"])
    share_valid_json = valid_json_count / total_calls

    avg_latency = sum(r["latency_sec"] for r in results) / total_calls
    avg_tokens_per_sec = sum(r["tokens_per_sec"] for r in results) / total_calls

    # Complaints metrics
    complaint_results = [r for r in results if r["task"] == "complaints"]
    comp_prec, comp_rec, comp_em, multi_cat_acc = 0.0, 0.0, 0.0, 0.0
    multi_count = 0

    if complaint_results:
        comp_prec = sum(r["metrics"].get("precision", 0.0) for r in complaint_results) / len(complaint_results)
        comp_rec = sum(r["metrics"].get("recall", 0.0) for r in complaint_results) / len(complaint_results)
        comp_em = sum(r["metrics"].get("exact_match", 0.0) for r in complaint_results) / len(complaint_results)
        multi_items = [r for r in complaint_results if r["metrics"].get("is_multi_category", 0.0) == 1.0]
        multi_count = len(multi_items)
        if multi_items:
            multi_cat_acc = sum(r["metrics"].get("multi_category_exact_match", 0.0) for r in multi_items) / len(multi_items)
        else:
            multi_cat_acc = 1.0

    # Sentiment metrics
    sentiment_results = [r for r in results if r["task"] == "sentiment"]
    sent_acc = 0.0
    if sentiment_results:
        sent_acc = sum(r["metrics"].get("accuracy", 0.0) for r in sentiment_results) / len(sentiment_results)

    return {
        "total_calls": total_calls,
        "valid_json_share": share_valid_json,
        "avg_latency_sec": avg_latency,
        "avg_tokens_per_sec": avg_tokens_per_sec,
        "complaints": {
            "total_items": len(complaint_results),
            "precision": comp_prec,
            "recall": comp_rec,
            "exact_match": comp_em,
            "multi_category_items": multi_count,
            "multi_category_accuracy": multi_cat_acc,
        },
        "sentiment": {
            "total_items": len(sentiment_results),
            "accuracy": sent_acc,
        },
    }


def compute_side_by_side_agreement(
    results_a: List[Dict[str, Any]], results_b: List[Dict[str, Any]]
) -> Dict[str, float]:
    map_b = {r["id"]: r for r in results_b}
    agreements: Dict[str, List[int]] = {"overall": [], "complaints": [], "sentiment": []}

    for item_a in results_a:
        item_id = item_a["id"]
        if item_id in map_b:
            item_b = map_b[item_id]
            pred_a = item_a["prediction"]
            pred_b = item_b["prediction"]
            match = 1 if pred_a == pred_b else 0
            agreements["overall"].append(match)
            if item_a["task"] in agreements:
                agreements[item_a["task"]].append(match)

    return {
        key: (sum(lst) / len(lst)) if lst else 1.0 for key, lst in agreements.items()
    }


def print_llm_summary(model_name: str, summary: Dict[str, Any], agreement: Optional[Dict[str, float]] = None):
    sep = "=" * 70
    print("\n" + sep)
    print(f" LLM EVALUATION SUMMARY: {model_name}")
    print(sep)
    print(f"Total Evaluated Calls           : {summary['total_calls']}")
    print(f"Valid JSON Output Share          : {summary['valid_json_share'] * 100:.2f}%")
    print(f"Average Seconds Per Answer       : {summary['avg_latency_sec']:.2f} s")
    print(f"Average Tokens Per Second        : {summary['avg_tokens_per_sec']:.2f} tok/s")
    print("-" * 70)
    print("TASK: COMPLAINTS")
    comp = summary["complaints"]
    print(f"  Total Complaints Items         : {comp['total_items']}")
    print(f"  Precision                      : {comp['precision'] * 100:.2f}%")
    print(f"  Recall                         : {comp['recall'] * 100:.2f}%")
    print(f"  Exact Match Accuracy           : {comp['exact_match'] * 100:.2f}%")
    print(f"  Multi-Category Call Accuracy   : {comp['multi_category_accuracy'] * 100:.2f}% (on {comp['multi_category_items']} calls)")
    print("-" * 70)
    print("TASK: SENTIMENT")
    sent = summary["sentiment"]
    print(f"  Total Sentiment Items          : {sent['total_items']}")
    print(f"  Sentiment Classification Acc   : {sent['accuracy'] * 100:.2f}%")

    if agreement:
        print("-" * 70)
        print("SIDE-BY-SIDE AGREEMENT WITH REFERENCE MODEL:")
        print(f"  Overall Model Agreement Rate   : {agreement.get('overall', 0.0) * 100:.2f}%")
        print(f"  Complaints Agreement Rate      : {agreement.get('complaints', 0.0) * 100:.2f}%")
        print(f"  Sentiment Agreement Rate       : {agreement.get('sentiment', 0.0) * 100:.2f}%")
    print(sep + "\n")


def main():
    args = parse_args()
    if args.mock:
        client_a = MockLLMClient()
    else:
        client_a = LLMClient(base_url=args.base_url, model=args.model, api_key_env=args.api_key_env)

    results_a = evaluate_dataset(client_a, args.data)
    summary_a = summarize_evaluation(results_a)

    agreement = None
    if args.compare_base_url and args.compare_model:
        if args.mock:
            client_b = MockLLMClient()
        else:
            client_b = LLMClient(
                base_url=args.compare_base_url,
                model=args.compare_model,
                api_key_env=args.api_key_env,
            )
        results_b = evaluate_dataset(client_b, args.data)
        agreement = compute_side_by_side_agreement(results_a, results_b)

    print_llm_summary(args.model, summary_a, agreement=agreement)

    if args.output:
        out_payload = {
            "model": args.model,
            "summary": summary_a,
            "agreement_with_comparison": agreement,
            "results": results_a,
        }
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(out_payload, f, indent=2, ensure_ascii=False)
        print(f"Report saved to {args.output}")


if __name__ == "__main__":
    main()

