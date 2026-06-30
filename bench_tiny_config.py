"""Benchmarks for tiny-config. Run with `python bench_tiny_config.py`."""

import json
import os
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import tiny_config as tc


def bench(name, fn, n=10_000):
    # warmup
    fn()
    t0 = time.perf_counter()
    for _ in range(n):
        fn()
    dt = (time.perf_counter() - t0) / n * 1e6
    print(f"  {name:30s} {dt:8.3f} µs/op")


def main():
    print("== tiny-config benchmarks (n=10,000) ==")

    cfg = {"a": {"b": {"c": 1}}, "x": [1, 2, 3]}

    def m_get():
        tc.get(cfg, "a.b.c")

    def m_set():
        d = {}
        tc.set(d, "a.b.c", 1)

    def m_merge():
        tc.merge({"a": {"b": 1, "c": 2}}, {"a": {"b": 99}})

    bench("get (3-level)", m_get)
    bench("set (3-level)", m_set)
    bench("merge (shallow)", m_merge)

    # file load benchmark
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as f:
        json.dump({"a": {"b": {"c": 1}}, "x": [1, 2, 3], "n": 42}, f)
        path = f.name

    try:
        def m_load():
            tc.load_file(path)
        bench("load_file (json)", m_load)
    finally:
        os.unlink(path)


if __name__ == "__main__":
    main()
