#!/usr/bin/env python3
"""
E2E reproducer + diagnostic test for issue #357.

Issue #357 claims `codedb_bundle` drops nested `arguments` for `codedb_outline`,
producing repeated `error: missing 'path' argument`.

This script drives the real codedb MCP over JSON-RPC stdio with several bundle
shapes and reports what the server actually does. It also verifies the issue
#357 fix: when a bundled op fails with a missing-arg error, the bundle wrapper
appends a `received keys: [...]` diagnostic so callers can self-diagnose
whether codedb dropped the field or the client sent it under the wrong name.

Findings (as of v0.2.5792 + #357 fix):
  * Nested `arguments: {path: "..."}` — works correctly, path preserved.
  * Inline `{tool, path: "..."}`     — works correctly, path preserved.
  * Wrong key `arguments: {file_path: "..."}` — fails with `missing 'path'`
    AND surfaces `received keys: [file_path]`.
  * No path at all `{tool}`           — fails with `missing 'path'` AND surfaces
    `received keys: [tool]`.

Conclusion: the alleged bug does not exist; the error fires only when the
bundle op genuinely lacks `path`. The diagnostic addresses the issue's
"Expected behavior" #2 (machine-readable diagnostics for malformed ops).

Usage:
  python3 scripts/test_issue_357_bundle_diagnostic.py [--binary PATH] [--project PATH]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

GREEN = "\033[32m"
RED = "\033[31m"
YELLOW = "\033[33m"
CYAN = "\033[36m"
BOLD = "\033[1m"
RESET = "\033[0m"

PASS = f"{GREEN}PASS{RESET}"
FAIL = f"{RED}FAIL{RESET}"


class MCPProcess:
    """Wraps codedb mcp subprocess; sends/receives JSON-RPC over stdio."""

    def __init__(self, binary: str, project: str) -> None:
        self.proc = subprocess.Popen(
            [binary, project, "mcp"],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd="/",
            text=True,
            bufsize=1,
        )
        self._id = 1
        self._lock = threading.Lock()
        self._lines: list[str] = []
        self._reader = threading.Thread(target=self._read_loop, daemon=True)
        self._reader.start()

    def _read_loop(self) -> None:
        assert self.proc.stdout
        for line in self.proc.stdout:
            line = line.strip()
            if line:
                with self._lock:
                    self._lines.append(line)

    def send(self, msg: dict[str, Any]) -> None:
        assert self.proc.stdin
        self.proc.stdin.write(json.dumps(msg) + "\n")
        self.proc.stdin.flush()

    def recv_id(self, req_id: int, timeout: float = 30.0) -> dict[str, Any] | None:
        deadline = time.monotonic() + timeout
        held: list[str] = []
        while time.monotonic() < deadline:
            with self._lock:
                pending = list(self._lines)
                self._lines.clear()
            for raw in pending:
                msg = json.loads(raw)
                if msg.get("id") == req_id:
                    with self._lock:
                        self._lines = held + self._lines
                    return msg
                held.append(raw)
            with self._lock:
                self._lines = held + self._lines
            held = []
            time.sleep(0.02)
        return None

    def initialize(self) -> bool:
        self.send({
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "issue-357-test", "version": "1"},
            },
        })
        resp = self.recv_id(1, timeout=10)
        if resp is None or "result" not in resp:
            return False
        self.send({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        return True

    def call(self, name: str, args: dict[str, Any], timeout: float = 30.0) -> dict[str, Any] | None:
        self._id += 1
        req_id = self._id
        self.send({
            "jsonrpc": "2.0",
            "id": req_id,
            "method": "tools/call",
            "params": {"name": name, "arguments": args},
        })
        return self.recv_id(req_id, timeout=timeout)

    def wait_for_scan(self, timeout: float = 60.0) -> bool:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            resp = self.call("codedb_status", {}, timeout=5.0)
            text = tool_text(resp)
            m = re.search(r"\boutlines:\s*(\d+)", text)
            if m and int(m.group(1)) > 0:
                return True
            time.sleep(0.5)
        return False

    def close(self) -> None:
        try:
            assert self.proc.stdin
            self.proc.stdin.close()
        except Exception:
            pass
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()


def tool_text(resp: dict[str, Any] | None) -> str:
    if resp is None:
        return ""
    content = resp.get("result", {}).get("content", [])
    return "\n".join(c.get("text", "") for c in content if isinstance(c, dict))


# ── Test cases ────────────────────────────────────────────────────────────────

def case(name: str, *, ok: bool, msg: str = "") -> tuple[str, bool, str]:
    return (name, ok, msg)


def assert_contains(text: str, needle: str, label: str) -> tuple[bool, str]:
    if needle in text:
        return (True, f"{label} present")
    return (False, f"{label} missing — got: {text[:200]!r}")


def assert_not_contains(text: str, needle: str, label: str) -> tuple[bool, str]:
    if needle not in text:
        return (True, f"{label} absent (good)")
    return (False, f"{label} unexpectedly present — got: {text[:200]!r}")


def run_tests(p: MCPProcess) -> list[tuple[str, bool, str]]:
    results: list[tuple[str, bool, str]] = []

    # Pick a couple of files that we know exist in the codedb repo so the
    # outline calls would succeed if path is preserved.
    p1, p2 = "src/main.zig", "src/mcp.zig"

    # ── 1. Nested args (MCP tools/call style) — should preserve path ──────────
    resp = p.call("codedb_bundle", {"ops": [
        {"tool": "codedb_outline", "arguments": {"path": p1}},
        {"tool": "codedb_outline", "arguments": {"path": p2}},
    ]})
    text = tool_text(resp)
    ok, msg = assert_not_contains(text, "missing 'path'", "[1] nested args: missing-path error")
    results.append(("nested args do NOT trigger missing-path", ok, msg))
    ok, msg = assert_contains(text, p1, f"[1] nested args: outline for {p1}")
    results.append(("nested args produce outline for op[0]", ok, msg))
    ok, msg = assert_contains(text, p2, f"[1] nested args: outline for {p2}")
    results.append(("nested args produce outline for op[1]", ok, msg))

    # ── 2. Inline args — should also preserve path ────────────────────────────
    resp = p.call("codedb_bundle", {"ops": [
        {"tool": "codedb_outline", "path": p1},
    ]})
    text = tool_text(resp)
    ok, msg = assert_not_contains(text, "missing 'path'", "[2] inline args: missing-path error")
    results.append(("inline args do NOT trigger missing-path", ok, msg))
    ok, msg = assert_contains(text, p1, f"[2] inline args: outline for {p1}")
    results.append(("inline args produce outline", ok, msg))

    # ── 3. Wrong key name — must fail AND surface the bad key ─────────────────
    resp = p.call("codedb_bundle", {"ops": [
        {"tool": "codedb_outline", "arguments": {"file_path": p1}},
    ]})
    text = tool_text(resp)
    ok, msg = assert_contains(text, "missing 'path'", "[3] wrong-key: missing-path error")
    results.append(("wrong key triggers missing-path (legit)", ok, msg))
    ok, msg = assert_contains(text, "received keys", "[3] wrong-key: received-keys diagnostic")
    results.append(("wrong key surfaces received-keys diagnostic", ok, msg))
    ok, msg = assert_contains(text, "file_path", "[3] wrong-key: bad key 'file_path' surfaced")
    results.append(("wrong key names the bad key in diagnostic", ok, msg))

    # ── 4. No args at all — must fail AND surface what was there ──────────────
    resp = p.call("codedb_bundle", {"ops": [
        {"tool": "codedb_outline"},
    ]})
    text = tool_text(resp)
    ok, msg = assert_contains(text, "missing 'path'", "[4] no-args: missing-path error")
    results.append(("no args triggers missing-path (legit)", ok, msg))
    ok, msg = assert_contains(text, "received keys", "[4] no-args: received-keys diagnostic")
    results.append(("no args surfaces received-keys diagnostic", ok, msg))
    ok, msg = assert_contains(text, "tool", "[4] no-args: 'tool' key surfaced")
    results.append(("no args lists 'tool' key in diagnostic", ok, msg))

    return results


def main() -> int:
    parser = argparse.ArgumentParser(description="Issue #357 reproducer + diagnostic test")
    parser.add_argument("--binary", default="zig-out/bin/codedb",
                        help="Path to codedb binary (default: zig-out/bin/codedb)")
    parser.add_argument("--project", default=os.getcwd(),
                        help="Absolute path to project to index (default: cwd)")
    args = parser.parse_args()

    binary = str(Path(args.binary).resolve())
    project = str(Path(args.project).resolve())

    if not Path(binary).exists():
        print(f"{RED}ERROR:{RESET} binary not found: {binary}")
        print("Run `zig build` first, or pass --binary /path/to/codedb")
        return 1

    print(f"\n{BOLD}issue-357 bundle diagnostic E2E{RESET}")
    print(f"  binary : {binary}")
    print(f"  project: {project}\n")

    p = MCPProcess(binary, project)
    try:
        if not p.initialize():
            print(f"{RED}initialize failed — server did not respond{RESET}")
            return 1
        if not p.wait_for_scan(timeout=60.0):
            print(f"{RED}scan never produced outlines — cannot run bundle tests{RESET}")
            return 1

        results = run_tests(p)
    finally:
        p.close()

    print(f"{CYAN}── Bundle path-preservation + diagnostic results ──{RESET}")
    passed = failed = 0
    for name, ok, msg in results:
        status = PASS if ok else FAIL
        detail = f"  {msg}" if msg else ""
        print(f"  {status}  {name}{detail}")
        if ok:
            passed += 1
        else:
            failed += 1

    print(f"\n{BOLD}Results: {passed}/{len(results)} passed{RESET}")
    if failed:
        print(f"{RED}{failed} test(s) failed.{RESET}")
        return 1
    print(f"{GREEN}All tests passed.{RESET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
