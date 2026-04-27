#!/usr/bin/env bash
# EverLoop Agent 一键启动脚本
# 使用 conda activate agent 环境运行

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "╔══════════════════════════════════════════╗"
echo "║       EverLoop Agent 启动器              ║"
echo "╚══════════════════════════════════════════╝"
echo ""

# 检查 conda 环境
if ! conda run -n agent python --version >/dev/null 2>&1; then
  echo "??  ????? 'agent' ? conda ??"
  echo "   ????: conda create -n agent python=3.11"
  exit 1
fi

BACKEND_HOST="${EVERLOOP_BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${EVERLOOP_BACKEND_PORT:-8001}"
BACKEND_PORT_SCAN="${EVERLOOP_BACKEND_PORT_SCAN:-50}"

# ??????
# 1) ??? EverLoop ??????????????/????
# 2) ?? __pycache__??????????
# 3) ???????? mock/web_search ?????????????? prompt?
# ??? EVERLOOP_STARTUP_CLEANUP=0 ?????? EVERLOOP_KILL_OLD_BACKENDS=0 ??????
if [ "${EVERLOOP_STARTUP_CLEANUP:-1}" = "1" ]; then
  echo "?? ????????/??/????..."
  CLEANUP_ARGS=(scripts/startup_cleanup.py --host "$BACKEND_HOST" --port-start "$BACKEND_PORT" --port-span "$BACKEND_PORT_SCAN")
  if [ "${EVERLOOP_KILL_OLD_BACKENDS:-1}" = "1" ]; then
    CLEANUP_ARGS+=(--kill-backends)
  fi
  if ! conda run -n agent python "${CLEANUP_ARGS[@]}"; then
    echo "??  ??????????????????? python scripts/startup_cleanup.py ??"
  fi
fi

# ????
echo "?? ?? Python ??..."
conda run -n agent pip install -r requirements.txt -q

# LLM API ??????????????/HTML???????????
# ??? EVERLOOP_CHECK_LLM=0 ???
if [ "${EVERLOOP_CHECK_LLM:-1}" = "1" ]; then
  echo "?? ???? LLM API ???..."
  if ! conda run -n agent python scripts/check_llm_health.py --timeout "${EVERLOOP_LLM_HEALTH_TIMEOUT:-8}"; then
    echo "??  ?? LLM API ????????? VPN/????IP ????.env ? LLM_ENDPOINT__/LLM_API_KEY__???????"
  fi
fi

BACKEND_WAIT_SECONDS="${EVERLOOP_BACKEND_WAIT_SECONDS:-120}"
BACKEND_ALREADY_RUNNING=0
PYTHON_BIN="${PYTHON_BIN:-python}"

run_python() {
  if command -v "$PYTHON_BIN" >/dev/null 2>&1; then
    "$PYTHON_BIN" "$@"
  else
    conda run -n agent python "$@"
  fi
}

PORT_SELECTION="$(run_python scripts/select_backend_port.py "$BACKEND_HOST" "$BACKEND_PORT" "$BACKEND_PORT_SCAN")"
set -- $PORT_SELECTION
BACKEND_PORT="$1"
BACKEND_PORT_MODE="$2"

if [ "$BACKEND_PORT_MODE" = "existing" ]; then
  echo "✅ 检测到后端已在 http://$BACKEND_HOST:$BACKEND_PORT 运行，复用现有服务"
  BACKEND_ALREADY_RUNNING=1
fi

BACKEND_ORIGIN="http://$BACKEND_HOST:$BACKEND_PORT"

# 启动后端
echo ""
if [ "$BACKEND_ALREADY_RUNNING" -eq 0 ]; then
  echo "🚀 启动后端服务 ($BACKEND_ORIGIN) ..."
  EVERLOOP_BACKEND_HOST="$BACKEND_HOST" EVERLOOP_BACKEND_PORT="$BACKEND_PORT" conda run -n agent python main.py &
  BACKEND_PID=$!
else
  BACKEND_PID=""
fi

# 等待后端就绪
echo "⏳ 等待后端就绪..."
i=1
while [ "$i" -le "$BACKEND_WAIT_SECONDS" ]; do
  if run_python scripts/check_backend_health.py "$BACKEND_HOST" "$BACKEND_PORT" true >/dev/null 2>&1; then
    echo "✅ 后端已就绪"
    break
  fi

  if [ -n "$BACKEND_PID" ] && ! kill -0 "$BACKEND_PID" 2>/dev/null; then
    echo "❌ 后端进程已退出，请查看上方日志"
    exit 1
  fi

  if [ $((i % 10)) -eq 0 ]; then
    echo "   仍在等待后端初始化... ($i/$BACKEND_WAIT_SECONDS)"
  fi

  sleep 1
  i=$((i + 1))
done

if [ "$i" -gt "$BACKEND_WAIT_SECONDS" ]; then
  echo "❌ 后端启动超时（等待 ${BACKEND_WAIT_SECONDS}s）：$BACKEND_ORIGIN"
  echo "   可设置 EVERLOOP_BACKEND_WAIT_SECONDS=180 延长等待时间。"
  if [ -n "$BACKEND_PID" ]; then
    if run_python scripts/check_backend_health.py "$BACKEND_HOST" "$BACKEND_PORT" false >/dev/null 2>&1; then
      echo "   检测到端口已有 HTTP 响应，保留后端进程以便查看日志。"
    else
      kill $BACKEND_PID 2>/dev/null
    fi
  fi
  exit 1
fi

# 启动前端
echo ""
echo "🎨 启动前端服务 (http://localhost:5173) ..."
cd frontend
if [ ! -d "node_modules" ]; then
  echo "📦 安装前端依赖..."
  npm install
fi
VITE_API_TARGET="$BACKEND_ORIGIN" VITE_API_BASE="$BACKEND_ORIGIN/api" npm run dev &
FRONTEND_PID=$!

echo ""
echo "════════════════════════════════════════════"
echo "✅ EverLoop Agent 已启动！"
echo ""
echo "   前端界面: http://localhost:5173"
echo "   后端 API: $BACKEND_ORIGIN"
echo "   API 文档: $BACKEND_ORIGIN/docs"
echo ""
echo "   按 Ctrl+C 停止所有服务"
echo "════════════════════════════════════════════"

# 等待用户中断
trap "echo ''; echo '👋 正在停止服务...'; if [ -n \"$BACKEND_PID\" ]; then kill $BACKEND_PID 2>/dev/null; fi; kill $FRONTEND_PID 2>/dev/null; exit 0" SIGINT SIGTERM

wait
