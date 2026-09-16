@echo off
rem ============================================================
rem  Rebuild Galgame Manager.exe from Launcher.cs
rem  Uses the C# compiler that ships with .NET Framework 4.x.
rem  Run this file only after editing Launcher.cs.
rem ============================================================
setlocal
cd /d "%~dp0.."
set CSC=%WINDIR%\Microsoft.NET\Framework64\v4.0.30319\csc.exe
if not exist "%CSC%" set CSC=%WINDIR%\Microsoft.NET\Framework\v4.0.30319\csc.exe
if not exist "%CSC%" (
    echo [ERROR] csc.exe not found. .NET Framework 4.x is required.
    pause
    exit /b 1
)
echo Compiling ...
"%CSC%" /nologo /target:winexe /platform:anycpu /optimize+ ^
    /win32icon:"assets\app_icon.ico" ^
    /out:"Galgame Manager.exe" ^
    /reference:System.Windows.Forms.dll ^
    "launcher\Launcher.cs" "launcher\AssemblyInfo.cs"
if errorlevel 1 (
    echo [ERROR] Build failed.
    pause
    exit /b 1
)
echo Done: Galgame Manager.exe
pause
