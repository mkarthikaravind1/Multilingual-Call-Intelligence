"""CLI for generating markdown SLA scorecard report: python -m evalkit.report"""

import argparse
import json
import os
import sys

from evalkit.report.generator import generate_markdown_report


def parse_args():
    parser = argparse.ArgumentParser(description="Generate Migration SLA Scorecard Markdown Report")
    parser.add_argument("--asr", type=str, default=None, help="Path to JSON output from evalkit.asr")
    parser.add_argument("--llm", type=str, default=None, help="Path to JSON output from evalkit.llm")
    parser.add_argument("--load", type=str, default=None, help="Path to JSON output from evalkit.load")
    parser.add_argument("--output", type=str, default="migration_report.md", help="Path to write markdown report")
    return parser.parse_args()


def load_json_if_exists(path):
    if not path or not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main():
    args = parse_args()
    asr_data = load_json_if_exists(args.asr)
    llm_data = load_json_if_exists(args.llm)
    load_data = load_json_if_exists(args.load)

    report_md = generate_markdown_report(
        asr_data=asr_data,
        llm_data=llm_data,
        load_data=load_data,
    )

    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(report_md)
        print(f"Report written to {args.output}")

    print("\n" + report_md)


if __name__ == "__main__":
    main()

