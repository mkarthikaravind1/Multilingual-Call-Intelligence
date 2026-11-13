"""Markdown SLA Scorecard and Model Comparison Report Generator."""

from dataclasses import dataclass
import json
import os
from typing import Any, Dict, List, Optional


@dataclass
class SLATarget:
    metric_name: str
    target_value: float
    unit: str
    operator: str  # ">=" or "<="
    achieved_value: Optional[float]
    passed: bool


TARGETS = [
    {"name": "Speech Words Right (1 - WER)", "target": 95.0, "unit": "%", "op": ">="},
    {"name": "Complaint Categories Match", "target": 92.0, "unit": "%", "op": ">="},
    {"name": "Several Categories on One Call", "target": 88.0, "unit": "%", "op": ">="},
    {"name": "Sentiment Classification Accuracy", "target": 90.0, "unit": "%", "op": ">="},
    {"name": "Transcript Line Latency (p95)", "target": 2.0, "unit": "s", "op": "<="},
    {"name": "Complaint Categories Latency (p95)", "target": 3.0, "unit": "s", "op": "<="},
    {"name": "Suggested Question Latency (p95)", "target": 1.5, "unit": "s", "op": "<="},
]


def check_sla(achieved: Optional[float], target: float, op: str) -> bool:
    if achieved is None:
        return False
    if op == ">=":
        return achieved >= target
    elif op == "<=":
        return achieved <= target
    return False


def generate_markdown_report(
    asr_data: Optional[Dict[str, Any]] = None,
    llm_data: Optional[Dict[str, Any]] = None,
    load_data: Optional[Dict[str, Any]] = None,
    title: str = "Automotive Call Analysis Model Migration Report",
) -> str:
    """Generate comprehensive markdown report comparing model metrics against company SLA targets."""
    # Extract values
    speech_wr = None
    if asr_data and "summaries" in asr_data and "OVERALL" in asr_data["summaries"]:
        speech_wr = asr_data["summaries"]["OVERALL"].get("words_right", 0.0) * 100.0

    complaint_acc = None
    multi_cat_acc = None
    sent_acc = None
    if llm_data and "summary" in llm_data:
        summ = llm_data["summary"]
        if "complaints" in summ:
            complaint_acc = summ["complaints"].get("exact_match", 0.0) * 100.0
            multi_cat_acc = summ["complaints"].get("multi_category_accuracy", 0.0) * 100.0
        if "sentiment" in summ:
            sent_acc = summ["sentiment"].get("accuracy", 0.0) * 100.0

    transcript_p95 = None
    complaint_lat_p95 = None
    question_lat_p95 = None

    if load_data:
        if "transcripts" in load_data:
            transcript_p95 = load_data["transcripts"].get("p95_latency_sec")
        if "llm" in load_data:
            complaint_lat_p95 = load_data["llm"].get("p95_latency_sec")
            # If dedicated question latency not tracked, use p50 of LLM as proxy or p95
            question_lat_p95 = load_data["llm"].get("p50_latency_sec")
    elif llm_data and "summary" in llm_data:
        complaint_lat_p95 = llm_data["summary"].get("avg_latency_sec")
        question_lat_p95 = (complaint_lat_p95 * 0.5) if complaint_lat_p95 else None

    # Map to target checks
    evaluated_targets = [
        SLATarget("Speech Words Right", 95.0, "%", ">=", speech_wr, check_sla(speech_wr, 95.0, ">=")),
        SLATarget("Complaint Categories", 92.0, "%", ">=", complaint_acc, check_sla(complaint_acc, 92.0, ">=")),
        SLATarget("Several Categories on One Call", 88.0, "%", ">=", multi_cat_acc, check_sla(multi_cat_acc, 88.0, ">=")),
        SLATarget("Sentiment", 90.0, "%", ">=", sent_acc, check_sla(sent_acc, 90.0, ">=")),
        SLATarget("Transcript Line Latency (p95)", 2.0, "s", "<=", transcript_p95, check_sla(transcript_p95, 2.0, "<=")),
        SLATarget("Complaint Categories Latency (p95)", 3.0, "s", "<=", complaint_lat_p95, check_sla(complaint_lat_p95, 3.0, "<=")),
        SLATarget("Suggested Question Latency (p95)", 1.5, "s", "<=", question_lat_p95, check_sla(question_lat_p95, 1.5, "<=")),
    ]

    all_passed = all(t.passed for t in evaluated_targets if t.achieved_value is not None)
    tested_count = sum(1 for t in evaluated_targets if t.achieved_value is not None)
    passed_count = sum(1 for t in evaluated_targets if t.passed)

    md = []
    md.append(f"# {title}\n")
    md.append("## Executive Decision Summary\n")
    if tested_count == 0:
        md.append("> **Status**: Pending Evaluation Data. No benchmark data supplied yet.\n")
    elif all_passed and tested_count == len(evaluated_targets):
        md.append("> **Status**: **READY FOR MIGRATION (PASS)**  \n> Self-hosted models satisfy all target accuracy and latency SLAs. Recommended to initiate shadow routing.\n")
    else:
        md.append(f"> **Status**: **NOT READY FOR MIGRATION ({passed_count}/{tested_count} Targets Met)**  \n> Self-hosted models currently miss one or more critical SLAs. Retain paid cloud fallback until gaps are closed.\n")

    md.append("## SLA Benchmark Scorecard\n")
    md.append("| Metric | Target | Operator | Achieved | Status |")
    md.append("| :--- | :--- | :---: | :--- | :---: |")

    for t in evaluated_targets:
        if t.achieved_value is None:
            ach_str = "Not Evaluated"
            st_str = "PENDING"
        else:
            ach_str = f"{t.achieved_value:.2f} {t.unit}"
            st_str = "PASSED" if t.passed else "**FAILED**"
        md.append(f"| {t.metric_name} | {t.target_value:.1f} {t.unit} | {t.operator} | {ach_str} | {st_str} |")

    # ASR Breakdown
    if asr_data and "summaries" in asr_data:
        md.append("\n## Speech-to-Text Performance by Language\n")
        md.append("| Language | Clips | Words Right | WER | CER | Avg Latency | RTF |")
        md.append("| :--- | :---: | :---: | :---: | :---: | :---: | :---: |")
        for lang, s in asr_data["summaries"].items():
            wr = f"{s.get('words_right', 0.0) * 100:.2f}%"
            wer = f"{s.get('wer', 0.0) * 100:.2f}%"
            cer = f"{s.get('cer', 0.0) * 100:.2f}%"
            lat = f"{s.get('avg_latency_sec', 0.0):.2f} s"
            rtf = f"{s.get('rtf', 0.0):.2f}x"
            md.append(f"| {lang} | {s.get('total_clips', 0)} | {wr} | {wer} | {cer} | {lat} | {rtf} |")

    # LLM Breakdown
    if llm_data and "summary" in llm_data:
        summ = llm_data["summary"]
        md.append("\n## LLM Task Accuracy & Side-by-Side Analysis\n")
        md.append(f"- **Valid JSON Share**: {summ.get('valid_json_share', 0.0) * 100:.2f}%")
        md.append(f"- **Average Inference Speed**: {summ.get('avg_tokens_per_sec', 0.0):.2f} tokens/s ({summ.get('avg_latency_sec', 0.0):.2f} s/answer)")
        if "complaints" in summ:
            c = summ["complaints"]
            md.append(f"- **Complaints Precision**: {c.get('precision', 0.0) * 100:.2f}%")
            md.append(f"- **Complaints Recall**: {c.get('recall', 0.0) * 100:.2f}%")
            md.append(f"- **Complaints Exact Match**: {c.get('exact_match', 0.0) * 100:.2f}%")
            md.append(f"- **Multi-Category Accuracy**: {c.get('multi_category_accuracy', 0.0) * 100:.2f}%")
        if "sentiment" in summ:
            s = summ["sentiment"]
            md.append(f"- **Sentiment Accuracy**: {s.get('accuracy', 0.0) * 100:.2f}%")

        if "agreement_with_comparison" in llm_data and llm_data["agreement_with_comparison"]:
            agr = llm_data["agreement_with_comparison"]
            md.append("\n### Agreement with Paid Cloud API\n")
            md.append(f"- **Overall Agreement**: {agr.get('overall', 0.0) * 100:.2f}%")
            md.append(f"- **Complaints Agreement**: {agr.get('complaints', 0.0) * 100:.2f}%")
            md.append(f"- **Sentiment Agreement**: {agr.get('sentiment', 0.0) * 100:.2f}%")

    return "\n".join(md) + "\n"

