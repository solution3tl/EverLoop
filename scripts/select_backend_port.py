import http.client
import json
import socket
import sys


def is_everloop_backend(host: str, port: int) -> bool:
    conn = http.client.HTTPConnection(host, port, timeout=0.5)
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
    try:
        data = json.loads(body)
    except json.JSONDecodeError:
        return "EverLoop Agent" in body
    return data.get("service") == "EverLoop Agent"


def is_free(host: str, port: int) -> bool:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((host, port))
        return True
    except OSError:
        return False
    finally:
        sock.close()


if __name__ == "__main__":
    host_arg = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
    start_arg = int(sys.argv[2]) if len(sys.argv) > 2 else 8001
    span_arg = int(sys.argv[3]) if len(sys.argv) > 3 else 50

    for candidate in range(start_arg, start_arg + span_arg):
        if is_everloop_backend(host_arg, candidate):
            print(candidate, "existing")
            raise SystemExit(0)

    for candidate in range(start_arg, start_arg + span_arg):
        if is_free(host_arg, candidate):
            print(candidate, "new")
            raise SystemExit(0)

    raise SystemExit(f"No reusable or free backend port found in {start_arg}-{start_arg + span_arg - 1}")
