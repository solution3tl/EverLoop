"""Check configured OpenAI-compatible LLM endpoints.

This is a lightweight diagnostic for cases where the model gateway returns an
HTML block/blacklist page instead of JSON.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from llm.model_config import MODEL_REGISTRY, get_default_config  # noqa: E402


def normalize_base_url(endpoint: str) -> str:
    return endpoint.rstrip("/").replace("/chat/completions", "")


def looks_like_html(text: str) -> bool:
    lower = (text or "").lstrip().lower()
    return lower.startswith("<!doctype") or lower.startswith("<html") or "<html" in lower[:500]


def classify_response(text: str) -> str:
    lower = text.lower()
    if looks_like_html(text):
        if "黑名单" in text or "禁止访问" in text or "vpn" in lower or "校园网" in text or "websaas" in lower:
            return "HTML_BLOCKED_BLACKLIST_OR_VPN"
        return "HTML_NOT_JSON"
    try:
        json.loads(text)
        return "OK_JSON"
    except json.JSONDecodeError:
        return "NOT_JSON"


def check_one(name: str, timeout: int) -> tuple[bool, str]:
    cfg = MODEL_REGISTRY[name]
    url = f"{normalize_base_url(cfg.base_url)}/chat/completions"
    payload = {
        "model": cfg.model_name,
        "messages": [{"role": "user", "content": "ping"}],
        "max_tokens": 4,
        "temperature": 0,
        "stream": False,
    }
    headers = {"Content-Type": "application/json"}
    if cfg.api_key and cfg.api_key != "none":
        headers["Authorization"] = f"Bearer {cfg.api_key}"

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            text = resp.read().decode("utf-8", errors="replace")
            status = resp.status
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", errors="replace")
        kind = classify_response(text)
        return False, f"HTTP {exc.code} {kind}: {text[:220]}"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"

    kind = classify_response(text)
    ok = status == 200 and kind == "OK_JSON"
    return ok, f"HTTP {status} {kind}: {text[:220]}"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="", help="model/provider name; default checks DEFAULT_MODEL")
    parser.add_argument("--all", action="store_true", help="check all configured models")
    parser.add_argument("--timeout", type=int, default=8)
    args = parser.parse_args()

    if args.all:
        names = list(MODEL_REGISTRY.keys())
    elif args.model:
        names = [args.model]
    else:
        names = [get_default_config().provider]

    failed = 0
    for name in names:
        if name not in MODEL_REGISTRY:
            print(f"[LLM] {name}: NOT_CONFIGURED")
            failed += 1
            continue
        cfg = MODEL_REGISTRY[name]
        ok, message = check_one(name, args.timeout)
        mark = "OK" if ok else "FAIL"
        print(f"[LLM] {mark} {name} -> {cfg.base_url}")
        print(f"      {message}")
        if not ok:
            failed += 1

    return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
