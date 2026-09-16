@echo off
rem ============================================================
rem  Galgame Manager 环境检测工具 —— 无黑框启动器（源码 + 重建脚本）
rem
rem  双击本文件 → 在本目录生成 "Galgame Manager环境检测工具.exe"
rem  生成后把那个 exe 复制回工具目录（与环境检测工具.ps1 放一起）。
rem  依赖：.NET Framework 4.x 自带的 csc.exe，无需安装任何东西。
rem
rem  本文件为 GBK/ANSI + CRLF 编码，请不要另存为 UTF-8 / LF。
rem ============================================================
setlocal
cd /d "%~dp0"
set CSC=%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe
if not exist "%CSC%" set CSC=%WINDIR%\Microsoft.NET\Framework\v4.0.30319\csc.exe
if not exist "%CSC%" (
    echo [ERROR] 找不到 csc.exe，需要 .NET Framework 4.x。
    pause
    exit /b 1
)
echo 正在编译 ...
"%CSC%" /nologo /target:winexe /platform:anycpu /optimize+ /out:"Galgame Manager环境检测工具.exe" /reference:System.Windows.Forms.dll "Launcher.cs"
if errorlevel 1 (
    echo [ERROR] 编译失败。
    pause
    exit /b 1
)
echo 完成：Galgame Manager环境检测工具.exe（复制回工具目录即可）
pause