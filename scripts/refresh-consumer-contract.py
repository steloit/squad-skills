#!/usr/bin/env python3
"""Regenerate the consumer-contract snapshot used by the doc-contract guard
(tests/test_api_paths_match_openapi.py).

The guard extracts every executable `api <METHOD> <resource-path>` call across the
skills, normalizes each through api.py's org mount (`/api/orgs/<org>` + resource-path,
query stripped, params collapsed to `{}`), and publishes the deduped subset as a
first-class, committed artifact — tests/fixtures/consumer-contract.json. This is the
consumer side of bi-directional contract testing (the consumer publishes the endpoint
subset it depends on) and the exact input a live-spec drift diff would consume.

Like scripts/refresh-openapi.sh, regeneration is explicit + reviewable (a committed
diff), NOT auto-written at test time — the guard asserts the committed file is in sync,
so a surface change shows up as a reviewed fixture diff.

Usage:  scripts/refresh-consumer-contract.py
"""
import importlib.util
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[1]


def _load_guard():
    """Load the guard module (it owns the extractor + normalization) by path; its dir
    is not a package and pytest is not on the path here."""
    src = ROOT / "tests" / "test_api_paths_match_openapi.py"
    spec = importlib.util.spec_from_file_location("doc_contract_guard", src)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main():
    guard = _load_guard()
    contract = guard.build_consumer_contract(ROOT)
    dest = ROOT / "tests" / "fixtures" / "consumer-contract.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(contract, indent=2) + "\n")
    print(f"Wrote {dest} ({len(contract)} endpoints).")


if __name__ == "__main__":
    main()
