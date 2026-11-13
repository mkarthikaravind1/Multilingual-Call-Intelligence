"""Unit tests for evalkit.report: Markdown report and SLA targets."""

from evalkit.report.generator import generate_markdown_report


def test_report_generation_all_passed():
    asr_data = {
        "summaries": {
            "ta": {"words_right": 0.96, "wer": 0.04, "cer": 0.03, "avg_latency_sec": 0.8, "rtf": 0.3},
            "OVERALL": {"words_right": 0.96, "wer": 0.04, "cer": 0.03, "avg_latency_sec": 0.8, "rtf": 0.3, "total_clips": 10},
        }
    }
    llm_data = {
        "summary": {
            "valid_json_share": 1.0,
            "avg_latency_sec": 1.2,
            "avg_tokens_per_sec": 120.0,
            "complaints": {
                "precision": 0.95,
                "recall": 0.93,
                "exact_match": 0.94,
                "multi_category_accuracy": 0.90,
            },
            "sentiment": {
                "accuracy": 0.92,
            },
        },
        "agreement_with_comparison": {
            "overall": 0.95,
            "complaints": 0.93,
            "sentiment": 0.97,
        },
    }
    load_data = {
        "transcripts": {"p95_latency_sec": 1.1},
        "llm": {"p95_latency_sec": 2.2, "p50_latency_sec": 1.0},
    }

    report = generate_markdown_report(asr_data, llm_data, load_data)
    assert "READY FOR MIGRATION (PASS)" in report
    assert "Speech Words Right" in report
    assert "95.0 %" in report
    assert "Several Categories on One Call" in report
    assert "PASSED" in report
    assert "Agreement with Paid Cloud API" in report


def test_report_generation_failed_target():
    asr_data = {
        "summaries": {
            "OVERALL": {"words_right": 0.89, "wer": 0.11, "cer": 0.10, "avg_latency_sec": 2.5, "rtf": 0.8, "total_clips": 10},
        }
    }
    report = generate_markdown_report(asr_data=asr_data)
    assert "NOT READY FOR MIGRATION" in report
    assert "**FAILED**" in report

