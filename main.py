"""
EverLoop Agent 后端启动入口
"""
import uvicorn
import sys
import os
import socket

# 确保项目根目录在 Python 路径中
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from api.router import app


def _get_port() -> int:
    raw = os.getenv("EVERLOOP_BACKEND_PORT") or os.getenv("PORT") or "8001"
    try:
        return int(raw)
    except ValueError:
        return 8001


def _port_is_available(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        return sock.connect_ex((host, port)) != 0


if __name__ == "__main__":
    host = os.getenv("EVERLOOP_BACKEND_HOST", "127.0.0.1")
    port = _get_port()
    if not _port_is_available(host, port):
        print(
            f"[ERROR] 后端端口已被占用: http://{host}:{port}\n"
            "        请关闭已有进程，或设置 EVERLOOP_BACKEND_PORT 使用其他端口。",
            file=sys.stderr,
        )
        sys.exit(98)

    uvicorn.run(
        app,
        host=host,
        port=port,
        reload=False,
        log_level="info",
    )
