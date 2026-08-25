"""
Simple concurrent load test for the Starcare chat API. No extra frameworks —
just asyncio + httpx (already a dependency via the openai package).

Usage:
    python load_test.py --url http://localhost:8000 --concurrency 200
    python load_test.py --url http://localhost:8000 --concurrency 500 --waves 3

Each "wave" fires --concurrency requests all at once (a burst, simulating
that many users hitting the endpoint at the same moment), waits for all of
them to finish, then prints latency and success-rate stats for that wave.

Each virtual user gets a unique user_id, so this also naturally avoids
tripping the per-user rate limiter (RATE_LIMIT_PER_MINUTE) or mixing up
chat sessions between "users".
"""

import argparse
import asyncio
import random
import time
from collections import Counter

import httpx

# Mix of caregiver/admin, answerable/unanswerable, single-shot and flow-style
# questions, so the test exercises retrieval, generation, and the fallback
# (no-LLM-call) path all under load — not just the fast path.
QUESTIONS = [
    ("caregiver", "Why can't I administer this medication?"),
    ("caregiver", "How do I create a variance report?"),
    ("caregiver", "What happens when a medication becomes overdue?"),
    ("caregiver", "Can I access the Admin module?"),
    ("caregiver", "How do I record blood pressure?"),
    ("admin", "How do I create a new role?"),
    ("admin", "How do I assign a house to a caregiver?"),
    ("admin", "How do I review a Medication Variance Report?"),
    ("admin", "How do I manage Azure users?"),
    ("admin", "Walk me through the full medication variance resolution flow"),
    ("caregiver", "asdkjh qwoiue random gibberish xyz not in any manual"),  # forces the fallback path
]


async def send_one(client: httpx.AsyncClient, idx: int, results: list):
    role, message = random.choice(QUESTIONS)
    user_id = f"loadtest-{idx}-{random.randint(0, 999_999)}"
    payload = {"user_id": user_id, "role": role, "message": message}

    start = time.perf_counter()
    try:
        r = await client.post("/api/v1/chat", json=payload, timeout=60)
        elapsed = time.perf_counter() - start
        results.append({"status": r.status_code, "elapsed": elapsed, "ok": r.status_code == 200})
    except Exception as e:
        elapsed = time.perf_counter() - start
        results.append({"status": f"error:{type(e).__name__}", "elapsed": elapsed, "ok": False})


async def run_wave(client: httpx.AsyncClient, concurrency: int):
    results: list = []
    tasks = [send_one(client, i, results) for i in range(concurrency)]
    wave_start = time.perf_counter()
    await asyncio.gather(*tasks)
    wave_elapsed = time.perf_counter() - wave_start
    return results, wave_elapsed


def summarize(results: list, wave_elapsed: float):
    total = len(results)
    ok_results = [r for r in results if r["ok"]]
    ok = len(ok_results)
    failed = total - ok

    print(f"Total requests:       {total}")
    print(f"Successful (200):     {ok}")
    print(f"Failed:               {failed}")

    if ok_results:
        latencies = sorted(r["elapsed"] for r in ok_results)

        def pct(p):
            idx = min(int(len(latencies) * p), len(latencies) - 1)
            return latencies[idx]

        print("Latency (successful requests, seconds):")
        print(
            f"  min={latencies[0]:.2f}  p50={pct(0.5):.2f}  "
            f"p95={pct(0.95):.2f}  p99={pct(0.99):.2f}  max={latencies[-1]:.2f}"
        )

    print(f"Wave wall-clock time: {wave_elapsed:.2f}s")
    print(f"Effective throughput: {total / wave_elapsed:.1f} req/s")

    if failed:
        error_counts = Counter(r["status"] for r in results if not r["ok"])
        print(f"Error breakdown:      {dict(error_counts)}")


async def main():
    parser = argparse.ArgumentParser(description="Load test the Starcare chat API")
    parser.add_argument("--url", default="http://localhost:8000", help="Base URL of the running server")
    parser.add_argument("--concurrency", type=int, default=200, help="Simultaneous requests per wave")
    parser.add_argument("--waves", type=int, default=1, help="How many bursts to run back-to-back")
    args = parser.parse_args()

    limits = httpx.Limits(max_connections=args.concurrency + 50, max_keepalive_connections=args.concurrency)

    async with httpx.AsyncClient(base_url=args.url, limits=limits) as client:
        for wave in range(1, args.waves + 1):
            print(f"\n=== Wave {wave}/{args.waves}: firing {args.concurrency} concurrent requests ===")
            results, wave_elapsed = await run_wave(client, args.concurrency)
            summarize(results, wave_elapsed)


if __name__ == "__main__":
    asyncio.run(main())