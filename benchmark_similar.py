"""Compare isolated, read-only local CONTENT LAB similarity endpoints."""

import argparse
import http.client
import json
import math
from concurrent.futures import ThreadPoolExecutor
from time import perf_counter
from urllib.parse import quote


def get(port: int, path: str) -> tuple[bytes, float]:
    started = perf_counter()
    connection = http.client.HTTPConnection("127.0.0.1", port, timeout=10)
    try:
        connection.request("GET", path)
        response = connection.getresponse()
        body = response.read()
        if response.status != 200:
            raise RuntimeError(f"HTTP {response.status} from port {port}")
        return body, (perf_counter() - started) * 1000
    finally:
        connection.close()


def measure(port: int, path: str, concurrency: int, requests: int) -> tuple[float, float, float]:
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        started = perf_counter()
        elapsed = sorted(executor.map(lambda _: get(port, path)[1], range(requests)))
        throughput = requests / (perf_counter() - started)
    return elapsed[math.ceil(requests * 0.5) - 1], elapsed[math.ceil(requests * 0.95) - 1], throughput


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline_port", type=int)
    parser.add_argument("optimized_port", type=int)
    parser.add_argument("content_type")
    parser.add_argument("content_id", type=int)
    parser.add_argument("--requests", type=int, default=32)
    args = parser.parse_args()
    for port in (args.baseline_port, args.optimized_port):
        if port not in range(1, 65536):
            parser.error("ports must be in 1..65535")
    if args.baseline_port == args.optimized_port:
        parser.error("use separate baseline and optimized instances")
    if not 16 <= args.requests <= 256:
        parser.error("--requests must be in 16..256")
    if args.content_id <= 0 or args.content_type not in {"movie", "tv"}:
        parser.error("content_type must be movie or tv and content_id must be positive")
    path = f"/api/contents/{quote(args.content_type, safe='')}/{args.content_id}/similar"
    versions = [("baseline", args.baseline_port), ("optimized", args.optimized_port)]
    baseline, optimized = (json.loads(get(port, path)[0]) for _, port in versions)
    if baseline != optimized:
        raise SystemExit("Response mismatch. Ensure both instances use the same fixture and cache state.")
    print("report,concurrency,requests,p50_ms,p95_ms,requests_per_second", flush=True)
    for concurrency in (1, 4, 8):
        for label, port in versions:
            for _ in range(4):
                get(port, path)
            p50, p95, throughput = measure(port, path, concurrency, args.requests)
            print(f"{label},{concurrency},{args.requests},{p50:.3f},{p95:.3f},{throughput:.2f}", flush=True)
        versions.reverse()


if __name__ == "__main__":
    main()
