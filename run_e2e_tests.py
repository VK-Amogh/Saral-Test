#!/usr/bin/env python3
"""
Saral AI — End-to-End Test Suite Standalone Runner
File: run_e2e_tests.py

Executes the comprehensive 4-tier E2E test suite and outputs structured pass/fail metrics:
- Tier 1: Category-Partition Feature Coverage (tests/e2e/test_tier1_feature_coverage.py)
- Tier 2: Boundary Value Analysis & Corner Cases (tests/e2e/test_tier2_boundaries_and_corners.py)
- Tier 3: Pairwise Subsystem Integrations (tests/e2e/test_tier3_pairwise_combinations.py)
- Tier 4: Real-World Application Workflows (tests/e2e/test_tier4_real_world_scenarios.py)

Usage:
    python run_e2e_tests.py              # Run all tiers
    python run_e2e_tests.py --tier 1     # Run Tier 1 only
    python run_e2e_tests.py --live       # Run against live servers (E2E_LIVE=1)
    python run_e2e_tests.py -v           # Verbose pytest output
"""

import os
import sys
import time
import argparse
import pytest
from typing import Dict, Any, List

TIER_CONFIG = {
    1: {
        "name": "Tier 1: Feature Coverage",
        "file": "tests/e2e/test_tier1_feature_coverage.py",
        "desc": "Category-Partition coverage (Auth, Chat, Tasks, Inputs, Downloads, Cleanup)"
    },
    2: {
        "name": "Tier 2: Boundaries & Corners",
        "file": "tests/e2e/test_tier2_boundaries_and_corners.py",
        "desc": "Edge cases, 3x OTP lockout, 180s timeouts, corrupt/oversize PDFs"
    },
    3: {
        "name": "Tier 3: Pairwise Combinations",
        "file": "tests/e2e/test_tier3_pairwise_combinations.py",
        "desc": "Cross-feature pipelines (Auth+Realtime, Scrubber+Verhoeff, Broker+SecretStr)"
    },
    4: {
        "name": "Tier 4: Real-World Scenarios",
        "file": "tests/e2e/test_tier4_real_world_scenarios.py",
        "desc": "Full user workflows (Aadhaar download, CAPTCHA recovery, OTP retry, Cancel)"
    }
}

class TestResultCollector:
    """Pytest plugin to count execution results in-process."""
    def __init__(self):
        self.passed = 0
        self.failed = 0
        self.skipped = 0
        self.errors = 0

    def pytest_runtest_logreport(self, report):
        if report.when == "call":
            if report.passed:
                self.passed += 1
            elif report.failed:
                self.failed += 1
            elif report.skipped:
                self.skipped += 1
        elif report.failed:
            self.errors += 1

def parse_args():
    parser = argparse.ArgumentParser(description="Saral AI E2E Test Suite Runner")
    parser.add_argument("--tier", type=int, choices=[1, 2, 3, 4], help="Execute a specific test tier only")
    parser.add_argument("--live", action="store_true", help="Execute against live servers (sets E2E_LIVE=1)")
    parser.add_argument("-v", "--verbose", action="store_true", help="Verbose pytest output")
    return parser.parse_args()

def run_tier_tests(target_file: str, verbose: bool, live: bool) -> Dict[str, Any]:
    if live:
        os.environ["E2E_LIVE"] = "1"
    else:
        os.environ.pop("E2E_LIVE", None)

    collector = TestResultCollector()
    args = [target_file, "-q", "--tb=short"]
    if verbose:
        args.append("-v")

    start_time = time.time()
    exit_code = pytest.main(args, plugins=[collector])
    duration = time.time() - start_time

    total_failed = collector.failed + collector.errors
    total_tests = collector.passed + total_failed + collector.skipped

    return {
        "exit_code": int(exit_code),
        "passed": collector.passed,
        "failed": total_failed,
        "skipped": collector.skipped,
        "total": total_tests,
        "duration": duration
    }

def print_report(results: Dict[int, Dict[str, Any]]):
    border = "=" * 88
    divider = "-" * 88

    print("\n" + border)
    print("                    SARAL AI — END-TO-END TEST SUITE EXECUTION REPORT")
    print(border)
    print(f" {'Tier':<8} | {'Tier Name':<28} | {'Total':<7} | {'Passed':<7} | {'Failed':<7} | {'Duration':<8}")
    print(divider)

    total_tests = 0
    total_passed = 0
    total_failed = 0
    total_duration = 0.0

    for tier_num, res in sorted(results.items()):
        name = TIER_CONFIG[tier_num]["name"]
        t_total = res["total"]
        t_passed = res["passed"]
        t_failed = res["failed"]
        t_dur = res["duration"]

        total_tests += t_total
        total_passed += t_passed
        total_failed += t_failed
        total_duration += t_dur

        status_marker = "PASS" if t_failed == 0 and t_total > 0 else "FAIL"
        print(f" Tier {tier_num:<3} | {name:<28} | {t_total:<7} | {t_passed:<7} | {t_failed:<7} | {t_dur:5.2f}s  [{status_marker}]")

    print(divider)
    overall_status = "ALL TESTS PASSED (100% SUCCESS RATE)" if total_failed == 0 and total_tests > 0 else f"{total_failed} TESTS FAILED"
    print(f" {'TOTAL':<8} | {'All Configured Tiers':<28} | {total_tests:<7} | {total_passed:<7} | {total_failed:<7} | {total_duration:5.2f}s")
    print(border)
    print(f" OVERALL STATUS: {overall_status}")
    print(border + "\n")

def main():
    args = parse_args()
    tiers_to_run = [args.tier] if args.tier else [1, 2, 3, 4]

    results: Dict[int, Dict[str, Any]] = {}
    any_failed = False

    print(f"Initializing Saral AI E2E Test Suite...")
    print(f"Execution Mode: {'Live Integration' if args.live else 'Specification Oracle Harness'}")
    print(f"Target Tiers: {tiers_to_run}")

    for tier_num in tiers_to_run:
        cfg = TIER_CONFIG[tier_num]
        print(f"\n[+] Executing {cfg['name']} ({cfg['file']})...")
        res = run_tier_tests(cfg["file"], verbose=args.verbose, live=args.live)
        results[tier_num] = res
        if res["failed"] > 0 or res["exit_code"] != 0:
            any_failed = True

    print_report(results)
    sys.exit(1 if any_failed else 0)

if __name__ == "__main__":
    main()
