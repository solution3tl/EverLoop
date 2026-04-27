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

set BACKEND_HOST=127.0.0.1
set BACKEND_PORT=8001
set BACKEND_ALREADY_RUNNING=0

powershell -NoProfile -Command "try { $r=Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 http://%BACKEND_HOST%:%BACKEND_PORT%/health; if ($r.StatusCode -eq 200 -and $r.Content -match 'EverLoop Agent') { exit 0 } else { exit 1 } } catch { exit 1 }" >nul 2>&1
if not errorlevel 1 (
    echo     检测到后端已在 http://%BACKEND_HOST%:%BACKEND_PORT% 运行，复用现有服务
    set BACKEND_ALREADY_RUNNING=1
) else (
    for /f %%P in ('powershell -NoProfile -Command "$hostName='%BACKEND_HOST%'; $start=[int]'%BACKEND_PORT%'; for ($p=$start; $p -lt $start+50; $p++) { $l=[System.Net.Sockets.TcpListener]::new([System.Net.IPAddress]::Parse($hostName), $p); try { $l.Start(); $l.Stop(); Write-Output $p; break } catch { try { $l.Stop() } catch {} } }"') do set BACKEND_PORT=%%P
)

set BACKEND_ORIGIN=http://%BACKEND_HOST%:%BACKEND_PORT%

REM 启动后端（新窗口）
if "%BACKEND_ALREADY_RUNNING%"=="0" (
    echo [2/4] 启动后端服务 %BACKEND_ORIGIN%...
    start "EverLoop-Backend" cmd /k "conda activate agent && set EVERLOOP_BACKEND_HOST=%BACKEND_HOST%&& set EVERLOOP_BACKEND_PORT=%BACKEND_PORT%&& python main.py"
) else (
    echo [2/4] 后端服务已就绪，跳过重复启动
)

REM 等待后端就绪
echo [3/4] 等待后端就绪...
for /l %%I in (1,1,20) do (
    powershell -NoProfile -Command "try { $r=Invoke-WebRequest -UseBasicParsing -TimeoutSec 2 '%BACKEND_ORIGIN%/health'; if ($r.StatusCode -eq 200) { exit 0 } else { exit 1 } } catch { exit 1 }" >nul 2>&1
    if not errorlevel 1 goto backend_ready
    timeout /t 1 /nobreak >nul
)
echo [错误] 后端启动超时：%BACKEND_ORIGIN%
pause
exit /b 1

:backend_ready

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

start "EverLoop-Frontend" cmd /k "set VITE_API_TARGET=%BACKEND_ORIGIN%&& set VITE_API_BASE=%BACKEND_ORIGIN%/api&& npm run dev"

echo.
echo ════════════════════════════════════════════
echo  EverLoop Agent 启动完成！
echo.
echo  前端界面: http://localhost:5173
echo  后端 API: %BACKEND_ORIGIN%
echo  API 文档: %BACKEND_ORIGIN%/docs
echo.
echo  关闭上方两个命令窗口可停止服务
echo ════════════════════════════════════════════
echo.

REM 自动打开浏览器
timeout /t 3 /nobreak >nul
start http://localhost:5173

pause
