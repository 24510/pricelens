@echo off
chcp 65001 >nul
setlocal
cd /d "%~dp0"

for %%I in ("%~dp0..") do set "ROOT=%%~fI"

set "PY=python"
if exist "%~dp0..\.venv\Scripts\python.exe" set "PY=%~dp0..\.venv\Scripts\python.exe"

echo ============================================
echo   PriceLens 一键打包
echo ============================================
echo   项目根：%ROOT%
echo   解释器：%PY%
echo.

echo [0/6] 结束可能仍在运行的程序 ...
taskkill /im PriceLens.exe /f >nul 2>nul

echo [1/6] 清理旧产物 ...
if exist "%~dp0output" rmdir /s /q "%~dp0output"

echo [2/6] PyInstaller 打包中（首次约 1-3 分钟，请耐心等待）...
"%PY%" -m PyInstaller --noconfirm --clean --distpath "%~dp0output" --workpath "%~dp0output\_build" "%~dp0pricelens.spec"
if errorlevel 1 goto :fail

rem ---- 定位产物（兼容不同 PyInstaller 行为）----
set "OUT=%~dp0output"
if not exist "%OUT%\PriceLens\PriceLens.exe" if exist "%~dp0dist\PriceLens\PriceLens.exe" set "OUT=%~dp0dist"
if not exist "%OUT%\PriceLens\PriceLens.exe" if exist "%ROOT%\dist\PriceLens\PriceLens.exe" set "OUT=%ROOT%\dist"
if not exist "%OUT%\PriceLens\PriceLens.exe" (
  echo *** 未找到生成的 PriceLens.exe，请把上方日志发我 ***
  goto :fail
)

echo [3/6] 复制前端资源 web\ ...
xcopy "%ROOT%\web" "%OUT%\PriceLens\web" /E /I /Y >nul
if errorlevel 1 goto :fail

echo [4/6] 复制说明文件 ...
copy /y "%ROOT%\config.example.ini" "%OUT%\PriceLens\config.example.ini" >nul
copy /y "%ROOT%\README.txt" "%OUT%\PriceLens\README.txt" >nul

echo [5/6] 清理数据目录（保持分发包纯净）...
if exist "%OUT%\PriceLens\PriceLensData" rmdir /s /q "%OUT%\PriceLens\PriceLensData"

echo [6/6] 生成分发包 zip ...
powershell -NoProfile -Command "Compress-Archive -Path '%OUT%\PriceLens' -DestinationPath '%OUT%\PriceLens_v1.0.0_win64.zip' -Force" >nul
if errorlevel 1 echo    （zip 生成失败，可手动压缩 %OUT%\PriceLens 文件夹）

echo.
echo ============================================
echo   打包完成
echo ============================================
echo   程序： %OUT%\PriceLens\PriceLens.exe
echo   分发： %OUT%\PriceLens_v1.0.0_win64.zip
echo.
echo   下一步：进入 PriceLens 文件夹，双击 PriceLens.exe
echo.
pause
exit /b 0

:fail
echo.
echo *** 打包失败：请把上方最后 20 行信息发我 ***
pause
exit /b 1