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
if ! conda run -n agent python --version &>/dev/null; then
  echo "⚠️  未找到名为 'agent' 的 conda 环境"
  echo "   请先运行: conda create -n agent python=3.11"
  exit 1
fi

# 安装依赖
echo "📦 检查 Python 依赖..."
conda run -n agent pip install -r requirements.txt -q

# 启动后端
echo ""
echo "🚀 启动后端服务 (http://localhost:8000) ..."
conda run -n agent python main.py &
BACKEND_PID=$!

# 等待后端就绪
echo "⏳ 等待后端就绪..."
for i in {1..20}; do
  if curl -sf http://localhost:8000/health &>/dev/null; then
    echo "✅ 后端已就绪"
    break
  fi
  sleep 1
  if [ $i -eq 20 ]; then
    echo "❌ 后端启动超时"
    kill $BACKEND_PID 2>/dev/null
    exit 1
  fi
done

# 启动前端
echo ""
echo "🎨 启动前端服务 (http://localhost:5173) ..."
cd frontend
if [ ! -d "node_modules" ]; then
  echo "📦 安装前端依赖..."
  npm install
fi
npm run dev &
FRONTEND_PID=$!

echo ""
echo "════════════════════════════════════════════"
echo "✅ EverLoop Agent 已启动！"
echo ""
echo "   前端界面: http://localhost:5173"
echo "   后端 API: http://localhost:8000"
echo "   API 文档: http://localhost:8000/docs"
echo ""
echo "   按 Ctrl+C 停止所有服务"
echo "════════════════════════════════════════════"

# 等待用户中断
trap "echo ''; echo '👋 正在停止服务...'; kill $BACKEND_PID $FRONTEND_PID 2>/dev/null; exit 0" SIGINT SIGTERM

wait
