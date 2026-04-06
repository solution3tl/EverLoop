@echo off
chcp 65001 >nul
title EverLoop Agent

echo ╔══════════════════════════════════════════╗
echo ║       EverLoop Agent 启动器              ║
echo ╚══════════════════════════════════════════╝
echo.

cd /d "%~dp0"

REM 检查 conda 环境
call conda run -n agent python --version >nul 2>&1
if errorlevel 1 (
    echo [错误] 未找到名为 'agent' 的 conda 环境
    echo 请先运行: conda create -n agent python=3.11
    pause
    exit /b 1
)

REM 安装 Python 依赖
echo [1/4] 安装 Python 依赖...
call conda run -n agent pip install -r requirements.txt -q
if errorlevel 1 (
    echo [警告] 部分依赖安装失败，尝试继续...
)

REM 启动后端（新窗口）
echo [2/4] 启动后端服务...
start "EverLoop-Backend" cmd /k "conda activate agent && python main.py"

REM 等待后端就绪
echo [3/4] 等待后端就绪...
timeout /t 5 /nobreak >nul

REM 安装/启动前端
echo [4/4] 启动前端服务...
cd frontend

if not exist "node_modules" (
    echo     安装前端依赖（首次运行需要一些时间）...
    call npm install
    if errorlevel 1 (
        echo [错误] 前端依赖安装失败，请确保已安装 Node.js
        pause
        exit /b 1
    )
)

start "EverLoop-Frontend" cmd /k "npm run dev"

echo.
echo ════════════════════════════════════════════
echo  EverLoop Agent 启动完成！
echo.
echo  前端界面: http://localhost:5173
echo  后端 API: http://127.0.0.1:8001
echo  API 文档: http://127.0.0.1:8001/docs
echo.
echo  关闭上方两个命令窗口可停止服务
echo ════════════════════════════════════════════
echo.

REM 自动打开浏览器
timeout /t 3 /nobreak >nul
start http://localhost:5173

pause
