"""Command-line interface for running traffic, fault scenarios, and correlation checks."""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import List, Optional

# Ensure demo-microservices root is on sys.path
root_dir = Path(__file__).resolve().parent.parent
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

from simulator.scenarios import ScenarioRunner

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] [%(name)s]: %(message)s",
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="tracemind-demo-cli",
        description="TraceMind Demo Microservices Traffic & Failure Injection CLI",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # 1. status
    subparsers.add_parser("status", help="Check health and active fault configs of all microservices")

    # 2. faults-reset
    subparsers.add_parser("faults-reset", help="Reset fault configurations across all microservices")

    # 3. correlate
    corr_parser = subparsers.add_parser("correlate", help="Trigger controlled correlation evaluation in TraceMind")
    corr_parser.add_argument("--window", type=int, default=300, help="Sliding window in seconds (default: 300)")

    # 4. traffic
    traffic_parser = subparsers.add_parser("traffic", help="Send normal customer checkout traffic")
    traffic_parser.add_argument("--count", type=int, default=10, help="Number of orders to send (default: 10)")
    traffic_parser.add_argument("--interval", type=float, default=0.2, help="Interval between orders in seconds (default: 0.2)")

    # 5. scenario
    scenario_parser = subparsers.add_parser("scenario", help="Run a controlled failure/recovery scenario")
    scenario_sub = scenario_parser.add_subparsers(dest="scenario_name", required=True)

    # scenario normal
    s_norm = scenario_sub.add_parser("normal", help="Reset faults and send normal steady-state traffic")
    s_norm.add_argument("--count", type=int, default=10, help="Number of requests (default: 10)")
    s_norm.add_argument("--interval", type=float, default=0.15, help="Interval in seconds (default: 0.15)")

    # scenario inventory-latency
    s_inv = scenario_sub.add_parser("inventory-latency", help="Inject latency spike in Inventory Service")
    s_inv.add_argument("--delay-ms", type=float, default=650.0, help="Artificial delay in ms (default: 650.0)")
    s_inv.add_argument("--requests", type=int, default=5, help="Number of requests during fault (default: 5)")
    s_inv.add_argument("--warmup", type=int, default=0, help="Normal warmup requests before fault (default: 0)")
    s_inv.add_argument("--no-correlate", action="store_true", help="Skip automatic correlation trigger after batch")

    # scenario payment-errors
    s_pay = scenario_sub.add_parser("payment-errors", help="Inject gateway error spike in Payment Service")
    s_pay.add_argument("--error-pct", type=float, default=100.0, help="Error percentage 0-100 (default: 100.0)")
    s_pay.add_argument("--status-code", type=int, default=502, help="HTTP status code (default: 502)")
    s_pay.add_argument("--requests", type=int, default=5, help="Number of requests during fault (default: 5)")
    s_pay.add_argument("--warmup", type=int, default=0, help="Normal warmup requests before fault (default: 0)")
    s_pay.add_argument("--no-correlate", action="store_true", help="Skip automatic correlation trigger after batch")

    # scenario recover
    s_rec = scenario_sub.add_parser("recover", help="Reset all faults and send verification traffic")
    s_rec.add_argument("--count", type=int, default=5, help="Number of requests (default: 5)")
    s_rec.add_argument("--interval", type=float, default=0.15, help="Interval in seconds (default: 0.15)")

    return parser


async def execute_cli(args: argparse.Namespace, runner: Optional[ScenarioRunner] = None) -> dict:
    """Execute parsed CLI command using ScenarioRunner and return structured output."""
    active_runner = runner or ScenarioRunner()

    if args.command == "status":
        return await active_runner.get_all_status()

    if args.command == "faults-reset":
        return await active_runner.reset_all_faults()

    if args.command == "correlate":
        res = await active_runner.trigger_correlation_evaluation(window_seconds=args.window)
        return {"correlation_result": res}

    if args.command == "traffic":
        summary = await active_runner.traffic.run_batch(count=args.count, interval_sec=args.interval)
        return {
            "total_requests": summary.total_requests,
            "confirmed": summary.confirmed_count,
            "failed": summary.failed_count,
            "avg_latency_ms": summary.avg_latency_ms,
            "max_latency_ms": summary.max_latency_ms,
            "requests_per_second": summary.requests_per_second,
        }

    if args.command == "scenario":
        if args.scenario_name == "normal":
            summary = await active_runner.run_normal_traffic(count=args.count, interval_sec=args.interval)
            return {
                "scenario": "normal",
                "total_requests": summary.total_requests,
                "confirmed": summary.confirmed_count,
                "failed": summary.failed_count,
                "avg_latency_ms": summary.avg_latency_ms,
            }

        if args.scenario_name == "inventory-latency":
            return await active_runner.run_inventory_latency_spike(
                delay_ms=args.delay_ms,
                requests=args.requests,
                warmup_count=args.warmup,
                trigger_correlation=not args.no_correlate,
            )

        if args.scenario_name == "payment-errors":
            return await active_runner.run_payment_error_spike(
                error_pct=args.error_pct,
                status_code=args.status_code,
                requests=args.requests,
                warmup_count=args.warmup,
                trigger_correlation=not args.no_correlate,
            )

        if args.scenario_name == "recover":
            return await active_runner.run_recovery(count=args.count, interval_sec=args.interval)

    raise ValueError(f"Unsupported command: {args.command}")


def main(argv: Optional[List[str]] = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    result = asyncio.run(execute_cli(args))
    print(json.dumps(result, indent=2, default=str))


if __name__ == "__main__":
    main()

