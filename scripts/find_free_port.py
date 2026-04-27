import socket
import sys


def find_free_port(host: str, start_port: int, span: int = 50) -> int:
    for port in range(start_port, start_port + span):
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind((host, port))
            return port
        except OSError:
            continue
        finally:
            sock.close()
    raise RuntimeError(f"No free port found in {start_port}-{start_port + span - 1}")


if __name__ == "__main__":
    host_arg = sys.argv[1] if len(sys.argv) > 1 else "127.0.0.1"
    start_arg = int(sys.argv[2]) if len(sys.argv) > 2 else 8001
    span_arg = int(sys.argv[3]) if len(sys.argv) > 3 else 50
    print(find_free_port(host_arg, start_arg, span_arg))
