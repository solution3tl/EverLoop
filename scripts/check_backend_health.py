import http.client
import json
import sys


def is_healthy(host: str, port: int, require_everloop: bool = False) -> bool:
    conn = http.client.HTTPConnection(host, port, timeout=2)
    try:
        conn.request("GET", "/health")
        resp = conn.getresponse()
        body = resp.read().decode("utf-8", errors="replace")
    except OSError:
        return False
    finally:
        conn.close()

    if resp.status != 200:
        return False
    if not require_everloop:
        return True
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return "EverLoop Agent" in body
    return data.get("service") == "EverLoop Agent"


if __name__ == "__main__":
    host_arg = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
    port_arg = int(sys.argv[2]) if len(sys.argv) > 2 else 8001
    require_arg = len(sys.argv) > 3 and sys.argv[3].lower() in {"1", "true", "yes"}
    raise SystemExit(0 if is_healthy(host_arg, port_arg, require_arg) else 1)
