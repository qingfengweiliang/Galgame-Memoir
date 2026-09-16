#Requires -Version 5.1
<#
================================================================================
 Galgame Memoir —— 一键环境检测与安装脚本（Windows 10 / 11, x64）
 文件名: setup_env.ps1      版本: 1.0      编码: UTF-8 with BOM
--------------------------------------------------------------------------------
 【本脚本会安装 / 处理的东西 —— 人工确认清单】

 A. Python 第三方包（必需；缺失时用 pip 自动安装，已装则跳过）
    A1. PySide6-Essentials   —— Qt6 界面运行时（提供 PySide6.QtCore/QtGui/QtWidgets）
        依据: help\README.md「## 依赖」= pip install PySide6 requests pillow
              repair\repair.bat:44-45 = pip install PySide6-Essentials requests pillow
              src\main.py:8、src\main.py:39
    A2. requests             —— 所有网络请求
        依据: src\net.py:16、src\random_cg_api.py:20
    A3. pillow               —— 图片解码 / 缩放 / 转码（AVIF 解码要求 Pillow >= 11.3）
        依据: src\config.py:26、src\theme_manager.py:18、src\random_cg_api.py:21

 B. Python 第三方包（可选；只有加 -WithOptional 才安装）
    B1. darkdetect           —— 系统深浅色回退；仅在 PySide6 缺 colorScheme（< 6.5）时使用
        依据: src\config.py:227、src\theme_manager.py:452
              （两处都被 try/except 包住，缺失不影响启动，只影响"跟随系统深浅色"）

 C. 系统级组件（默认只检测；只有加 -FixSystem 且以管理员身份运行才会下载安装）
    C1. .NET Framework 4.x   —— 运行 Galgame Manager.exe（C# 启动器）
        依据: launcher\build_exe.bat:7-12、launcher\Launcher.cs、
              Galgame Manager.exe 内含 "v4.0.30319" + mscorlib 引用；Win10/11 已内置 4.8
    C2. VC++ 2015-2022 x64 运行库（msvcp140 / vcruntime140）
        说明: PySide6 的 wheel 自带 msvcp140.dll / vcruntime140.dll / vcruntime140_1.dll，
              通常【不需要】单独安装；仅当系统目录和 PySide6 目录都找不到时才提示

 D. 只检测、不安装（脚本不代劳，但会给出明确结论与处理建议）
    D1. Python 解释器本身（要求 >= 3.9）—— 不安装、不升级、不卸载、不改 PATH
        缺失时只提示项目自带安装包: python安装包\python-3.14.7-amd64.exe
    D2. 中文字体 Microsoft YaHei / Segoe UI Emoji
        依据: src\theme.py:502、src\theme.py:1024、src\random_cg_viewer.py:251-256
    D3. 网络连通性（Bangumi / VNDB / Steam / SteamGridDB / AnimeTrace / SauceNAO / CG 图源）
        依据: src\net.py:69,165,247,345,354,461,486,535,603、src\random_cg_api.py
    D4. CG 根目录（默认 E:\cg存储，可在程序设置里改）
        依据: src\config.py:41、data\settings.json 的 "cg_root"
    D5. API Key / Token（sgdb_key / bgm_token / sauce_key）—— 在程序「设置 → API」里填
        依据: src\config.py:103,116,421、data\settings.json

 【本脚本绝不会做的事】
    × 不安装 / 升级 / 卸载 Python 解释器，不改 PATH、不改注册表里的 Python 关联
    × 不修改 src\ 下任何源码，不替换 Galgame Manager.exe，不动 backup\
    × 不覆盖 data\settings.json、data\galgame.db（只读取 settings.json 里的 cg_root）
    × 不执行 repair.bat（两者互不干扰，脚本只负责把环境准备好）
    × 不删除任何已有文件（data 目录下的写权限测试文件用后即删）

 【幂等性】
    每一步都是"先检测、后动作"：已满足的项直接跳过并打印版本；重复运行安全。

 【退出码】
    0 = 环境就绪
    2 = Python 缺失或版本过低（需人工处理）
    3 = 依赖缺失 / 安装失败
    4 = 安装后校验失败
    5 = 系统组件缺失（需 -FixSystem + 管理员，或手动安装）
================================================================================
#>

[CmdletBinding()]
param(
    # 项目根目录（默认：本脚本所在目录）
    [string]   $ProjectRoot = '',
    # 指定要使用的 Python（默认：自动在 PATH 与常见目录里找第一个可用的 3.9+）
    [string]   $PythonExe   = '',
    # pip 镜像源（默认清华；加 -UseOfficialIndex 走官方 PyPI）
    [string]   $Mirror      = 'https://pypi.tuna.tsinghua.edu.cn/simple',
    [switch]   $UseOfficialIndex,
    # 需要代理时传入，例如 -Proxy http://127.0.0.1:7890
    [string]   $Proxy       = '',
    # 同时安装可选包 darkdetect
    [switch]   $WithOptional,
    # 强制重装已存在的包（--force-reinstall）
    [switch]   $ForceReinstall,
    # 安装位置：Interpreter=装进解释器自身（默认，和 repair.bat 一致）/ CurrentUser=加 --user
    [ValidateSet('Interpreter', 'CurrentUser')]
    [string]   $Scope       = 'Interpreter',
    # 允许脚本下载安装 .NET Framework 4.8 / VC++ 运行库（需要管理员）
    [switch]   $FixSystem,
    # 跳过系统级组件检测
    [switch]   $SkipSystemCheck,
    # 只检测与校验，绝不安装任何东西
    [switch]   $VerifyOnly,
    # 校验通过后顺便启动程序
    [switch]   $Launch,
    # 只跑镜像测速并退出（GUI 的「测速」按钮走这里；不需要 Python）
    [switch]   $OnlyMirrorTest,
    # 跳过镜像测速，直接用 -Mirror（失败再回退官方源）
    [switch]   $SkipMirrorProbe,
    # 自定义候选镜像列表（默认：官方 PyPI 主站 + 阿里云 + 清华 + 腾讯云 + 中科大 + 华为云）
    [string[]] $MirrorList      = @(),
    # 单个镜像的测速超时（毫秒）
    [int]      $MirrorTimeoutMs = 4000,
    # 高级：覆盖默认的必需包清单（自测用，例如 -Packages six）
    [string[]] $Packages    = @(),
    # 日志文件（默认写到 %TEMP%）
    [string]   $LogFile     = ''
)

$script:VERSION  = '1.0'
$script:StepNo   = 0
$script:Checks   = New-Object System.Collections.ArrayList
$script:Problems = New-Object System.Collections.ArrayList
$script:Py       = ''
$script:LogPath  = ''
$script:ExitCode = 0
$script:RootNote = ''

# 5.1 下 Invoke-WebRequest 默认可能不是 TLS1.2，先补上
try {
    [System.Net.ServicePointManager]::SecurityProtocol =
        [System.Net.ServicePointManager]::SecurityProtocol -bor [System.Net.SecurityProtocolType]::Tls12
} catch { }

# ==============================================================================
# 输出 / 记录
# ==============================================================================
function Write-Log {
    param(
        [string] $Text,
        [ValidateSet('INFO', 'OK', 'WARN', 'ERROR', 'STEP', 'HEAD')]
        [string] $Level = 'INFO'
    )
    $stamp  = (Get-Date).ToString('HH:mm:ss')
    $prefix = '[INFO]'
    $color  = 'Gray'
    switch ($Level) {
        'OK'    { $prefix = '[ OK ]'; $color = 'Green' }
        'WARN'  { $prefix = '[WARN]'; $color = 'Yellow' }
        'ERROR' { $prefix = '[FAIL]'; $color = 'Red' }
        'STEP'  { $prefix = '[STEP]'; $color = 'Cyan' }
        'HEAD'  { $prefix = '[====]'; $color = 'White' }
    }
    $line = '{0} {1} {2}' -f $stamp, $prefix, $Text
    Write-Host $line -ForegroundColor $color
    if ($script:LogPath) {
        try { Add-Content -LiteralPath $script:LogPath -Value $line -Encoding UTF8 } catch { }
    }
}

function Write-Step {
    param([string] $Text)
    $script:StepNo++
    Write-Host ''
    Write-Log ('======== 步骤 {0}: {1} ========' -f $script:StepNo, $Text) 'STEP'
}

function Register-Check {
    param(
        [string] $Name,
        [ValidateSet('OK', 'WARN', 'FAIL')] [string] $State,
        [string] $Detail = ''
    )
    [void]$script:Checks.Add([pscustomobject]@{ Name = $Name; State = $State; Detail = $Detail })
    $msg = $Name
    if ($Detail) { $msg = '{0}  —— {1}' -f $Name, $Detail }
    if ($State -eq 'OK')   { Write-Log $msg 'OK' }
    if ($State -eq 'WARN') { Write-Log $msg 'WARN' }
    if ($State -eq 'FAIL') { Write-Log $msg 'ERROR'; [void]$script:Problems.Add($Name) }
}

# ==============================================================================
# 进程 / 系统工具
# ==============================================================================
function Invoke-Exe {
    param([string] $Exe, [string[]] $ArgList)
    $code = -1
    $text = ''
    try {
        $text = (& $Exe @ArgList 2>&1 | Out-String)
        $code = $LASTEXITCODE
        if ($null -eq $code) { $code = 0 }
    } catch {
        $text = $_.Exception.Message
        $code = -1
    }
    return [pscustomobject]@{ Code = [int]$code; Text = ([string]$text).Trim() }
}

function Invoke-Py {
    param([string[]] $ArgList)
    return Invoke-Exe -Exe $script:Py -ArgList $ArgList
}

function Test-Admin {
    try {
        $id = [System.Security.Principal.WindowsIdentity]::GetCurrent()
        $pr = New-Object System.Security.Principal.WindowsPrincipal($id)
        return $pr.IsInRole([System.Security.Principal.WindowsBuiltInRole]::Administrator)
    } catch { return $false }
}

function Find-ProjectRootUpwards {
    # 工具可能被放在项目根的子目录里（例如 <项目根>\Galgame Manager环境检测工具\），
    # 所以从 $StartDir 起向上逐层找"同时含 src\main.py 与 data\"的那一层。
    param([string] $StartDir, [int] $MaxUp = 6)
    $dir = $StartDir
    for ($i = 0; $i -le $MaxUp; $i++) {
        if (-not $dir) { break }
        $hasMain = Test-Path -LiteralPath (Join-Path $dir 'src\main.py')
        $hasData = Test-Path -LiteralPath (Join-Path $dir 'data')
        if ($hasMain -and $hasData) { return $dir }
        $parent = Split-Path -Parent $dir
        if (-not $parent -or $parent -eq $dir) { break }
        $dir = $parent
    }
    return $null
}

function Install-DotNet48 {
    if (-not (Test-Admin)) {
        Write-Log '安装 .NET Framework 4.8 需要管理员权限：请以管理员身份重开 PowerShell，再加 -FixSystem 重跑。' 'ERROR'
        return $false
    }
    $url = 'https://go.microsoft.com/fwlink/?linkid=2088631'
    $dst = Join-Path $env:TEMP 'ndp48-x86-x64-allos-enu.exe'
    Write-Log ('下载 .NET Framework 4.8: {0}' -f $url) 'INFO'
    try {
        Invoke-WebRequest -Uri $url -OutFile $dst -UseBasicParsing -TimeoutSec 900 -ErrorAction Stop
    } catch {
        Write-Log ('下载失败: {0}' -f $_.Exception.Message) 'ERROR'
        Write-Log '可手动下载安装: https://dotnet.microsoft.com/download/dotnet-framework/net48' 'INFO'
        return $false
    }
    Write-Log '静默安装 .NET Framework 4.8（几分钟，可能提示重启）...' 'INFO'
    $p = Start-Process -FilePath $dst -ArgumentList '/q', '/norestart' -Wait -PassThru
    Write-Log ('安装程序退出码: {0}  (0/3010 表示成功，3010=需重启)' -f $p.ExitCode) 'INFO'
    return ($p.ExitCode -eq 0 -or $p.ExitCode -eq 3010)
}

function Install-VCRedist {
    if (-not (Test-Admin)) {
        Write-Log '安装 VC++ 运行库需要管理员权限：请以管理员身份重开 PowerShell，再加 -FixSystem 重跑。' 'ERROR'
        return $false
    }
    $url = 'https://aka.ms/vs/17/release/vc_redist.x64.exe'
    $dst = Join-Path $env:TEMP 'vc_redist.x64.exe'
    Write-Log ('下载 VC++ 2015-2022 x64 运行库: {0}' -f $url) 'INFO'
    try {
        Invoke-WebRequest -Uri $url -OutFile $dst -UseBasicParsing -TimeoutSec 900 -ErrorAction Stop
    } catch {
        Write-Log ('下载失败: {0}' -f $_.Exception.Message) 'ERROR'
        return $false
    }
    $p = Start-Process -FilePath $dst -ArgumentList '/install', '/quiet', '/norestart' -Wait -PassThru
    Write-Log ('安装程序退出码: {0}  (0/3010 表示成功)' -f $p.ExitCode) 'INFO'
    return ($p.ExitCode -eq 0 -or $p.ExitCode -eq 3010)
}

# ==============================================================================
# 镜像测速：主站（官方 PyPI）+ 备用镜像，并发探测，取最快
# ==============================================================================
function Get-MirrorCandidates {
    if ($MirrorList -and $MirrorList.Count -gt 0) {
        $custom = @()
        foreach ($u in $MirrorList) {
            if ($u -and $u.Trim() -ne '') {
                $url = $u.Trim()
                $name = $url
                try { $name = ([uri]$url).Host } catch { }
                $custom += [pscustomobject]@{ Name = $name; Url = $url }
            }
        }
        return $custom
    }
    return @(
        [pscustomobject]@{ Name = '官方 PyPI(主站)'; Url = 'https://pypi.org/simple' }
        [pscustomobject]@{ Name = '阿里云';          Url = 'https://mirrors.aliyun.com/pypi/simple' }
        [pscustomobject]@{ Name = '清华 TUNA';       Url = 'https://pypi.tuna.tsinghua.edu.cn/simple' }
        [pscustomobject]@{ Name = '腾讯云';          Url = 'https://mirrors.cloud.tencent.com/pypi/simple' }
        [pscustomobject]@{ Name = '中科大';          Url = 'https://pypi.mirrors.ustc.edu.cn/simple' }
        [pscustomobject]@{ Name = '华为云';          Url = 'https://repo.huaweicloud.com/repository/pypi/simple' }
    )
}

function Start-MirrorProbe {
    param([string] $Url, [int] $TimeoutMs = 4000)
    # 取 six 的索引页：体积很小、所有 PyPI 镜像都一定收录；HEAD 在部分源上会被拒，所以用 GET
    $probeUrl = $Url.TrimEnd('/') + '/six/'
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        $req = [System.Net.HttpWebRequest]::Create($probeUrl)
        $req.Method           = 'GET'
        $req.Timeout          = $TimeoutMs
        $req.ReadWriteTimeout = $TimeoutMs
        $req.UserAgent        = 'pip/24.0'
        $req.AllowAutoRedirect = $true
        $iar = $req.BeginGetResponse($null, $null)
        return [pscustomobject]@{ Url = $Url; Req = $req; Iar = $iar; SW = $sw; Failed = $false }
    } catch {
        $sw.Stop()
        return [pscustomobject]@{ Url = $Url; Req = $null; Iar = $null; SW = $sw; Failed = $true }
    }
}

function Complete-MirrorProbe {
    param($Probe, [int] $TimeoutMs = 4000)
    if ($Probe.Failed -or -not $Probe.Iar) {
        return [pscustomobject]@{ Url = $Probe.Url; Ms = -1; Ok = $false; State = '不可达' }
    }
    try {
        if (-not $Probe.Iar.AsyncWaitHandle.WaitOne($TimeoutMs + 2000, $false)) {
            try { $Probe.Req.Abort() } catch { }
            $Probe.SW.Stop()
            return [pscustomobject]@{ Url = $Probe.Url; Ms = -1; Ok = $false; State = '超时' }
        }
        $resp = $Probe.Req.EndGetResponse($Probe.Iar)
        $st   = $resp.GetResponseStream()
        $buf  = New-Object byte[] 2048
        $null = $st.Read($buf, 0, $buf.Length)   # 只读一小块，够判断"能下"
        $st.Close(); $resp.Close()
        $Probe.SW.Stop()
        return [pscustomobject]@{ Url = $Probe.Url; Ms = [int]$Probe.SW.ElapsedMilliseconds; Ok = $true; State = 'OK' }
    } catch {
        $Probe.SW.Stop()
        return [pscustomobject]@{ Url = $Probe.Url; Ms = -1; Ok = $false; State = '不可达' }
    }
}

function Test-MirrorTcp {
    # HTTP 栈被防火墙/代理按下时的兜底：只测 TCP 443 握手时延
    param([string] $Url, [int] $TimeoutMs = 3000)
    try {
        $u = [uri]$Url
        $port = 443
        if ($u.Port -gt 0) { $port = $u.Port }
        $sw  = [System.Diagnostics.Stopwatch]::StartNew()
        $tcp = New-Object System.Net.Sockets.TcpClient
        $iar = $tcp.BeginConnect($u.Host, $port, $null, $null)
        $ok  = $false
        if ($iar.AsyncWaitHandle.WaitOne($TimeoutMs, $false)) {
            try { $tcp.EndConnect($iar); $ok = $tcp.Connected } catch { $ok = $false }
        }
        $sw.Stop()
        try { $tcp.Close() } catch { }
        return [pscustomobject]@{ Ok = $ok; Ms = [int]$sw.ElapsedMilliseconds }
    } catch {
        return [pscustomobject]@{ Ok = $false; Ms = -1 }
    }
}

function Invoke-MirrorProbe {
    # 并发探测所有候选源 -> 打印测速表 -> 返回"可用源（按耗时升序）"
    $cands = @(Get-MirrorCandidates)
    Write-Log ('镜像测速：并发探测 {0} 个源（超时 {1}s，GET <镜像>/simple/six/）...' -f `
               $cands.Count, [math]::Round($MirrorTimeoutMs / 1000.0, 1)) 'INFO'

    $probes  = @()
    foreach ($c in $cands) { $probes += (Start-MirrorProbe -Url $c.Url -TimeoutMs $MirrorTimeoutMs) }

    $results = @()
    $i = 0
    foreach ($pr in $probes) {
        $r = Complete-MirrorProbe -Probe $pr -TimeoutMs $MirrorTimeoutMs
        $r | Add-Member -NotePropertyName Name -NotePropertyValue $cands[$i].Name -Force
        $results += $r
        if ($r.Ok) {
            Write-Log ('    测速 {0,-16} {1,7} ms    {2}' -f $r.Name, $r.Ms, $r.Url) 'INFO'
        } else {
            Write-Log ('    测速 {0,-16} {1,-8} {2}' -f $r.Name, $r.State, $r.Url) 'WARN'
        }
        $i++
    }

    $ranked = @($results | Where-Object { $_.Ok } | Sort-Object Ms)

    if ($ranked.Count -eq 0) {
        # HTTP 全部失败（常见于只放行代理的机器）-> 退化成 TCP 握手时延排序
        Write-Log 'HTTP 探测全部失败，改用 TCP 443 握手时延排序（兜底）...' 'WARN'
        $tcpResults = @()
        foreach ($c in $cands) {
            $t = Test-MirrorTcp -Url $c.Url -TimeoutMs 3000
            $tcpResults += [pscustomobject]@{ Name = $c.Name; Url = $c.Url; Ok = $t.Ok; Ms = $t.Ms; State = $(if ($t.Ok) { 'OK' } else { '不可达' }) }
        }
        foreach ($r in $tcpResults) {
            if ($r.Ok) { Write-Log ('    TCP  {0,-16} {1,7} ms    {2}' -f $r.Name, $r.Ms, $r.Url) 'INFO' }
            else       { Write-Log ('    TCP  {0,-16} {1,-8} {2}' -f $r.Name, $r.State, $r.Url) 'WARN' }
        }
        $ranked = @($tcpResults | Where-Object { $_.Ok } | Sort-Object Ms)
    }

    if ($ranked.Count -gt 0) {
        Write-Log ('最快源: {0}   ({1} ms)   {2}' -f $ranked[0].Name, $ranked[0].Ms, $ranked[0].Url) 'OK'
    } else {
        Write-Log '所有候选源都不可达。' 'WARN'
    }
    return $ranked
}

# ==============================================================================
# 步骤 0: 定位项目 / 初始化日志
# ==============================================================================
if (-not $ProjectRoot -or $ProjectRoot.Trim() -eq '') {
    if ($PSScriptRoot) { $ProjectRoot = $PSScriptRoot } else { $ProjectRoot = (Get-Location).Path }
    $foundRoot = Find-ProjectRootUpwards -StartDir $ProjectRoot
    if ($foundRoot -and $foundRoot -ne $ProjectRoot) {
        $script:RootNote = ('工具目录是 {0}，已自动定位项目根目录: {1}' -f $ProjectRoot, $foundRoot)
        $ProjectRoot = $foundRoot
    }
}
if (-not (Test-Path -LiteralPath $ProjectRoot)) {
    Write-Host ('[FAIL] 项目目录不存在: {0}' -f $ProjectRoot) -ForegroundColor Red
    exit 1
}
$ProjectRoot = (Resolve-Path -LiteralPath $ProjectRoot).Path

if (-not $LogFile -or $LogFile.Trim() -eq '') {
    $LogFile = Join-Path $env:TEMP ('galgame_setup_{0}.log' -f (Get-Date).ToString('yyyyMMdd_HHmmss'))
}
$script:LogPath = $LogFile
try {
    Set-Content -LiteralPath $script:LogPath -Encoding UTF8 -ErrorAction Stop `
        -Value ('Galgame Memoir setup log  ' + (Get-Date).ToString('yyyy-MM-dd HH:mm:ss'))
} catch { $script:LogPath = '' }

$isAdmin = Test-Admin

Write-Host ''
Write-Host '====================================================================' -ForegroundColor DarkCyan
Write-Host ('  Galgame Memoir · 环境检测与安装脚本 v{0}  (Windows / PowerShell)' -f $script:VERSION) -ForegroundColor Cyan
Write-Host '====================================================================' -ForegroundColor DarkCyan
Write-Host ('  项目目录 : {0}' -f $ProjectRoot)
Write-Host ('  日志文件 : {0}' -f $LogFile)
$adminText = '否  (装 Python 包不需要；只有 -FixSystem 需要)'
if ($isAdmin) { $adminText = '是' }
Write-Host ('  管理员   : {0}' -f $adminText)
$modeText = '检测 -> 安装 -> 校验'
if ($VerifyOnly) { $modeText = '只检测 + 校验（不会安装任何东西）' }
Write-Host ('  运行模式 : {0}' -f $modeText)
Write-Host ''
Write-Log '脚本开始运行。' 'INFO'
if ($script:RootNote) { Write-Log $script:RootNote 'INFO' }

# ==============================================================================
# 步骤 1: 项目结构检查
# ==============================================================================
Write-Step '检查项目结构是否完整'

$hardFiles = @('src\main.py', 'src\config.py', 'data')
foreach ($rel in $hardFiles) {
    $p = Join-Path $ProjectRoot $rel
    if (Test-Path -LiteralPath $p) { Write-Log ('存在: {0}' -f $rel) 'OK' }
    else { Write-Log ('缺少关键文件/目录: {0}' -f $rel) 'ERROR'; $script:ExitCode = 1 }
}
if ($script:ExitCode -eq 1) {
    Write-Log '项目根目录不正确（-ProjectRoot 应指向含 src\main.py 的那个文件夹），已中止。' 'ERROR'
    exit 1
}

$softFiles = @('Galgame Manager.exe', 'repair\repair.bat', 'launcher\build_exe.bat',
               'data\settings.json', 'assets\app_icon.ico', 'python安装包\python-3.14.7-amd64.exe')
foreach ($rel in $softFiles) {
    $p = Join-Path $ProjectRoot $rel
    if (Test-Path -LiteralPath $p) { Write-Log ('存在: {0}' -f $rel) 'OK' }
    else { Register-Check ('项目文件 {0}' -f $rel) 'WARN' '未找到（不影响直接跑源码，但影响对应启动方式/功能）' }
}

# ==============================================================================
# 步骤 1.5: 仅镜像测速（-OnlyMirrorTest；GUI 的「测速」按钮走这里，不需要 Python）
# ==============================================================================
if ($OnlyMirrorTest) {
    Write-Step '镜像测速（只测速，不安装任何东西）'
    $rankedOnly = @(Invoke-MirrorProbe)
    if ($rankedOnly.Count -gt 0) {
        Register-Check '镜像测速' 'OK' ('最快: {0} ({1} ms)' -f $rankedOnly[0].Name, $rankedOnly[0].Ms)
        Write-Log ('推荐使用: {0}' -f $rankedOnly[0].Url) 'INFO'
    } else {
        Register-Check '镜像测速' 'WARN' '所有候选镜像均不可达（安装时会回退官方 PyPI）'
    }
    Write-Host ''
    Write-Log '仅测速模式结束。' 'INFO'
    exit 0
}

# ==============================================================================
# 步骤 2: Python 解释器检测（只检测，不安装）
# ==============================================================================
Write-Step '检测 Python 解释器（要求 >= 3.9；本脚本不安装 Python）'

function New-PythonCandidates {
    $list = New-Object System.Collections.ArrayList
    if ($PythonExe -and $PythonExe.Trim() -ne '') { [void]$list.Add($PythonExe.Trim()) }
    foreach ($name in @('python.exe', 'python3.exe', 'py.exe')) {
        $c = Get-Command $name -ErrorAction SilentlyContinue
        if ($c -and $c.Source) { [void]$list.Add($c.Source) }
    }
    $patterns = @()
    if ($env:LOCALAPPDATA) { $patterns += (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python3*\python.exe') }
    $patterns += 'C:\Python3*\python.exe'
    $patterns += 'C:\Program Files\Python3*\python.exe'
    foreach ($pat in $patterns) {
        try {
            Get-Item -Path $pat -ErrorAction SilentlyContinue | ForEach-Object { [void]$list.Add($_.FullName) }
        } catch { }
    }
    return @($list | Select-Object -Unique)
}

$probeCode = "import sys;print('%d.%d.%d' % sys.version_info[:3]);print(sys.executable);print(1 if sys.maxsize > 2**32 else 0)"
$script:PyInfo = $null

foreach ($cand in (New-PythonCandidates)) {
    if (-not (Test-Path -LiteralPath $cand)) {
        if ($PythonExe -and $cand -eq $PythonExe.Trim()) { Write-Log ('指定的 Python 不存在: {0}' -f $cand) 'WARN' }
        continue
    }
    $item = Get-Item -LiteralPath $cand -ErrorAction SilentlyContinue
    if ($item -and $item.Length -eq 0) {
        Write-Log ('跳过 0 字节假壳（Microsoft Store 别名）: {0}' -f $cand) 'WARN'
        continue
    }
    $r = Invoke-Exe -Exe $cand -ArgList @('-c', $probeCode)
    if ($r.Code -ne 0) {
        Write-Log ('跳过（无法运行代码，退出码 {0}）: {1}' -f $r.Code, $cand) 'WARN'
        continue
    }
    $ls = @($r.Text -split "`r?`n" | Where-Object { $_.Trim() -ne '' })
    if ($ls.Count -lt 3) { Write-Log ('跳过（输出异常）: {0}' -f $cand) 'WARN'; continue }
    $ver = $ls[0].Trim()
    $parts = $ver.Split('.')
    if ($parts.Count -lt 2) { continue }
    $major = 0; $minor = 0
    [void][int]::TryParse($parts[0], [ref]$major)
    [void][int]::TryParse($parts[1], [ref]$minor)
    if ($major -ne 3 -or $minor -lt 9) {
        Write-Log ('跳过（版本 {0} 低于 3.9）: {1}' -f $ver, $cand) 'WARN'
        continue
    }
    $script:PyInfo = [pscustomobject]@{
        Path    = $cand
        Version = $ver
        Exe     = $ls[1].Trim()
        Is64    = ($ls[2].Trim() -eq '1')
    }
    break
}

if (-not $script:PyInfo) {
    Write-Log '没有找到可用的 Python 3.9+ 解释器。' 'ERROR'
    Write-Host ''
    Write-Host '  脚本按约定【不会安装 Python 解释器】，请手工处理（任选一种）：' -ForegroundColor Yellow
    Write-Host '   1) 用项目自带的安装包（推荐，版本已知可用）：' -ForegroundColor Yellow
    $bundled = @()
    try { $bundled = @(Get-ChildItem -LiteralPath (Join-Path $ProjectRoot 'python安装包') -Filter '*.exe' -ErrorAction SilentlyContinue) } catch { }
    if ($bundled.Count -gt 0) {
        foreach ($b in $bundled) { Write-Host ('        {0}' -f $b.FullName) -ForegroundColor Yellow }
        Write-Host '      安装时务必勾选 "Add Python to PATH"，装完重开一个 PowerShell 再跑本脚本。' -ForegroundColor Yellow
    } else {
        Write-Host '       python安装包\ 下没有安装包，请到 https://www.python.org/downloads/ 下载 3.9+ (64-bit)' -ForegroundColor Yellow
    }
    Write-Host '   2) 从 python.org 下载 3.9+ 64 位安装包，勾选 Add Python to PATH。' -ForegroundColor Yellow
    Write-Host '   3) 若已装但不在 PATH：用 -PythonExe "D:\Python\python.exe" 指定路径再跑。' -ForegroundColor Yellow
    Write-Host ''
    Register-Check 'Python 3.9+ 解释器' 'FAIL' '未找到可用的解释器'
    exit 2
}

$script:Py = $script:PyInfo.Path
$pyText = '{0}  ({1})' -f $script:PyInfo.Version, $script:PyInfo.Path
if ($script:PyInfo.Is64) {
    Register-Check 'Python 解释器' 'OK' $pyText
} else {
    Register-Check 'Python 解释器' 'WARN' ($pyText + '  <-- 32 位解释器，PySide6 可能没有对应 wheel')
}
# 注: 这里不打印 sys.executable（中文路径在 5.1 控制台会乱码），路径上面已经报过。

$pyDir  = Split-Path -Parent $script:Py
$pywPath = Join-Path $pyDir 'pythonw.exe'
if (Test-Path -LiteralPath $pywPath) {
    Register-Check 'pythonw.exe（启动器优先使用）' 'OK' $pywPath
} else {
    Register-Check 'pythonw.exe（启动器优先使用）' 'WARN' '同目录没有 pythonw.exe，启动器会退回 python.exe（会闪一下黑框）'
}
$pathPyw = Get-Command 'pythonw.exe' -ErrorAction SilentlyContinue
if ($pathPyw -and $pathPyw.Source -and (Split-Path -Parent $pathPyw.Source) -ne $pyDir) {
    Register-Check 'python / pythonw 一致性' 'WARN' ('PATH 里的 pythonw 在 {0}，与本次使用的 python 不同目录' -f $pathPyw.Source)
}

# ==============================================================================
# 步骤 3: pip 检测
# ==============================================================================
Write-Step '检测 pip（用于安装第三方包）'

$pipOk = $false
$r = Invoke-Py -ArgList @('-m', 'pip', '--version')
if ($r.Code -eq 0) {
    $pipOk = $true
    Register-Check 'pip' 'OK' (@($r.Text -split "`r?`n")[0])
} else {
    Write-Log 'pip 不可用，尝试 python -m ensurepip --upgrade ...' 'WARN'
    if (-not $VerifyOnly) {
        $e = Invoke-Py -ArgList @('-m', 'ensurepip', '--upgrade')
        if ($e.Code -eq 0) {
            $r = Invoke-Py -ArgList @('-m', 'pip', '--version')
            if ($r.Code -eq 0) { $pipOk = $true; Register-Check 'pip' 'OK' (@($r.Text -split "`r?`n")[0]) }
        }
    }
    if (-not $pipOk) {
        Register-Check 'pip' 'FAIL' '不可用（ensurepip 也没修好）'
        Write-Log '处理建议：重装 Python 时勾选 pip；或用 get-pip.py 手工安装后重跑本脚本。' 'INFO'
        exit 3
    }
}

# ==============================================================================
# 步骤 4: 第三方包检测
# ==============================================================================
Write-Step '检测 Python 第三方包'

$defaultPackages = @(
    [pscustomobject]@{ Key = 'PySide6';    PipName = 'PySide6-Essentials'; Import = 'PySide6';    Required = $true;  Purpose = 'Qt6 界面运行时';         Source = 'help\README.md 依赖 / repair\repair.bat:44' }
    [pscustomobject]@{ Key = 'requests';   PipName = 'requests';           Import = 'requests';   Required = $true;  Purpose = '全部网络请求';           Source = 'src\net.py:16' }
    [pscustomobject]@{ Key = 'pillow';     PipName = 'pillow';             Import = 'PIL';        Required = $true;  Purpose = '图片解码/缩放/转码';     Source = 'src\config.py:26' }
    [pscustomobject]@{ Key = 'darkdetect'; PipName = 'darkdetect';         Import = 'darkdetect'; Required = $false; Purpose = '系统深浅色回退（可选）'; Source = 'src\config.py:227' }
)

$pkgDefs = @()
if ($Packages.Count -gt 0) {
    Write-Log ('使用 -Packages 覆盖默认清单: {0}' -f ($Packages -join ', ')) 'WARN'
    foreach ($n in $Packages) {
        if ($n.Trim()) {
            $pkgDefs += [pscustomobject]@{ Key = $n.Trim(); PipName = $n.Trim(); Import = $n.Trim(); Required = $true; Purpose = '自定义'; Source = '-Packages 参数' }
        }
    }
} else {
    $pkgDefs = $defaultPackages
}

function Get-PackageInfo {
    param([string] $ImportName)
    $code = "import importlib;m=importlib.import_module('" + $ImportName + "');print(getattr(m,'__version__','unknown'))"
    $rr = Invoke-Py -ArgList @('-c', $code)
    if ($rr.Code -eq 0) {
        return [pscustomobject]@{ Installed = $true; Version = (@($rr.Text -split "`r?`n")[0]).Trim() }
    }
    return [pscustomobject]@{ Installed = $false; Version = '' }
}

$missing = New-Object System.Collections.ArrayList
foreach ($d in $pkgDefs) {
    if (-not $d.Required -and -not $WithOptional) {
        Write-Log ('{0}: 可选包，未启用（要装请加 -WithOptional）' -f $d.Key) 'INFO'
        continue
    }
    $info = Get-PackageInfo -ImportName $d.Import
    if ($info.Installed) {
        if ($d.Import -eq 'PySide6') {
            $sub = Invoke-Py -ArgList @('-c', 'import PySide6.QtCore, PySide6.QtGui, PySide6.QtWidgets')
            if ($sub.Code -ne 0) {
                Register-Check ('{0} ({1})' -f $d.Key, $d.PipName) 'FAIL' '能 import PySide6，但 QtCore/QtGui/QtWidgets 子模块异常，需要重装'
                [void]$missing.Add($d)
                continue
            }
        }
        Register-Check ('{0} ({1})' -f $d.Key, $d.PipName) 'OK' ('已安装，版本 {0}   [{1}]' -f $info.Version, $d.Purpose)
    } else {
        Register-Check ('{0} ({1})' -f $d.Key, $d.PipName) 'WARN' ('未安装   [{0}]' -f $d.Purpose)
        [void]$missing.Add($d)
    }
}

# ==============================================================================
# 步骤 5: 安装缺失依赖
# ==============================================================================
if ($missing.Count -eq 0) {
    Write-Log '所有必需依赖都已就绪，无需安装。' 'OK'
} elseif ($VerifyOnly) {
    Write-Log ('检测到 {0} 个依赖缺失，但当前是 -VerifyOnly，跳过安装。' -f $missing.Count) 'WARN'
    $script:ExitCode = 3
} else {
    $pkgsToInstall = @($missing | ForEach-Object { $_.PipName })
    Write-Step ('安装缺失依赖: {0}' -f ($pkgsToInstall -join ', '))

    $baseArgs = @('-m', 'pip', 'install', '--disable-pip-version-check', '--timeout', '30', '--retries', '5')
    if ($Scope -eq 'CurrentUser') { $baseArgs += '--user' }
    if ($Proxy -and $Proxy.Trim() -ne '') { $baseArgs += @('--proxy', $Proxy.Trim()) }
    if ($ForceReinstall) { $baseArgs += '--force-reinstall' }

    $indexList = New-Object System.Collections.ArrayList
    if ($UseOfficialIndex) {
        [void]$indexList.Add('')
        Write-Log '已指定 -UseOfficialIndex：只走官方 PyPI。' 'INFO'
    } elseif ($SkipMirrorProbe) {
        if ($Mirror -and $Mirror.Trim() -ne '') { [void]$indexList.Add($Mirror.Trim()) }
        [void]$indexList.Add('')
        Write-Log '已指定 -SkipMirrorProbe：跳过测速，直接用给定源（失败再回退官方 PyPI）。' 'INFO'
    } else {
        # 自动测速：主站(官方 PyPI) + 备用镜像，从最快的开始，其余按速度依次作为回退
        $rankedMirrors = @(Invoke-MirrorProbe)
        foreach ($rm in $rankedMirrors) {
            if (-not $indexList.Contains($rm.Url)) { [void]$indexList.Add($rm.Url) }
        }
        if (-not $indexList.Contains('')) { [void]$indexList.Add('') }   # 官方源保底
        $chain = @()
        foreach ($ix in $indexList) {
            if ($ix -eq '') { $chain += '官方 PyPI(默认)' } else { $chain += ([uri]$ix).Host }
        }
        Write-Log ('安装将按此顺序尝试 {0} 个源: {1}' -f $indexList.Count, ($chain -join '  ->  ')) 'INFO'
    }

    $ok = $false
    $triedUserFallback = $false
    while (-not $ok) {
        foreach ($idx in $indexList) {
            $pargs = @() + $baseArgs
            $srcName = '默认 PyPI'
            if ($idx -ne '') { $pargs += @('-i', $idx); $srcName = $idx }
            $pargs += $pkgsToInstall

            Write-Log ('尝试从 {0} 安装 ...' -f $srcName) 'INFO'
            Write-Host ('    {0} -m pip install {1}   [源: {2}]' -f $script:Py, ($pkgsToInstall -join ' '), $srcName) -ForegroundColor DarkGray
            if ($script:LogPath) {
                & $script:Py @pargs 2>&1 | Tee-Object -FilePath $script:LogPath -Append | ForEach-Object { Write-Host ('    {0}' -f $_) -ForegroundColor DarkGray }
            } else {
                & $script:Py @pargs 2>&1 | ForEach-Object { Write-Host ('    {0}' -f $_) -ForegroundColor DarkGray }
            }
            $code = $LASTEXITCODE
            if ($code -eq 0) {
                $ok = $true
                Write-Log ('从 {0} 安装成功。' -f $srcName) 'OK'
                break
            }
            Write-Log ('从 {0} 安装失败（pip 退出码 {1}）。' -f $srcName, $code) 'WARN'
        }
        if ($ok) { break }
        if (-not $triedUserFallback -and $Scope -eq 'Interpreter') {
            $triedUserFallback = $true
            Write-Log '两个源都失败，自动改用 --user（装到当前用户目录）再试一轮 ...' 'WARN'
            $baseArgs += '--user'
            continue
        }
        break
    }

    if (-not $ok) {
        Write-Log '依赖安装失败，脚本中止。' 'ERROR'
        $me = $MyInvocation.MyCommand.Path
        Write-Host ''
        Write-Host '  排查顺序（任一步成功后重跑本脚本即可，脚本是幂等的）：' -ForegroundColor Yellow
        Write-Host ('   1) 网络/代理: powershell -ExecutionPolicy Bypass -File "{0}" -Proxy http://127.0.0.1:7890' -f $me) -ForegroundColor Yellow
        Write-Host ('   2) 换官方源: powershell -ExecutionPolicy Bypass -File "{0}" -UseOfficialIndex' -f $me) -ForegroundColor Yellow
        Write-Host  '   3) 权限不足: 加 -Scope CurrentUser 装到用户目录' -ForegroundColor Yellow
        Write-Host ('   4) 代理环境变量: 先执行 $env:HTTPS_PROXY="http://127.0.0.1:7890" 再跑脚本') -ForegroundColor Yellow
        Write-Host ('   5) 残留损坏包: "{0}" -m pip uninstall -y {1}  然后重跑' -f $script:Py, ($pkgsToInstall -join ' ')) -ForegroundColor Yellow
        Write-Host ('   6) 回滚说明: 本脚本只做 pip 安装，回滚 = 卸载刚装的包: "{0}" -m pip uninstall -y {1}' -f $script:Py, ($pkgsToInstall -join ' ')) -ForegroundColor Yellow
        Write-Host ''
        exit 3
    }

    Write-Step '安装后复核'
    foreach ($d in $missing) {
        $info = Get-PackageInfo -ImportName $d.Import
        if ($info.Installed) { Register-Check ('{0} 安装后复核' -f $d.Key) 'OK' ('版本 {0}' -f $info.Version) }
        else { Register-Check ('{0} 安装后复核' -f $d.Key) 'FAIL' 'pip 报告成功但仍无法 import，建议先 uninstall 再重跑' }
    }
    if ($script:Problems.Count -gt 0) {
        Write-Log '安装后复核未全部通过，请按上面的建议处理后重跑。' 'ERROR'
        exit 4
    }
}

# ==============================================================================
# 步骤 6: 系统级组件检测
# ==============================================================================
if ($SkipSystemCheck) {
    Write-Step '系统级组件检测（已用 -SkipSystemCheck 跳过）'
} else {
    Write-Step '检测系统级组件（.NET / VC++ / 字体 / 网络 / 数据目录）'

    # ---- 6.1 Windows 版本 ----
    try {
        $osv = [System.Environment]::OSVersion.Version
        if ($osv.Major -ge 10) {
            Register-Check 'Windows 版本' 'OK' ('{0}（PySide6 6.x 要求 Win10 1809+ / Win11）' -f $osv.ToString())
        } else {
            Register-Check 'Windows 版本' 'FAIL' ('{0} 过旧，PySide6 6.x 需要 Windows 10 1809 及以上' -f $osv.ToString())
        }
    } catch { Register-Check 'Windows 版本' 'WARN' '无法读取 OS 版本' }

    # ---- 6.2 .NET Framework 4.x（启动 Galgame Manager.exe 需要）----
    $relKey  = 'HKLM:\SOFTWARE\Microsoft\NET Framework Setup\NDP\v4\Full'
    $release = $null
    try { $release = (Get-ItemProperty -LiteralPath $relKey -ErrorAction Stop).Release } catch { $release = $null }
    if ($release -and [int]$release -ge 528040) {
        Register-Check '.NET Framework 4.x' 'OK' ('已安装 4.8+（Release={0}），可运行 Galgame Manager.exe' -f $release)
    } elseif ($release -and [int]$release -ge 378389) {
        Register-Check '.NET Framework 4.x' 'OK' ('已安装 4.x（Release={0}），建议升级到 4.8' -f $release)
    } else {
        $fixed = $false
        if ($FixSystem) { $fixed = Install-DotNet48 }
        if ($fixed) {
            Register-Check '.NET Framework 4.x' 'OK' '已通过 -FixSystem 安装（若提示重启，重启后再跑一次校验）'
        } else {
            Register-Check '.NET Framework 4.x' 'FAIL' '未检测到 4.x；手动安装 https://dotnet.microsoft.com/download/dotnet-framework/net48 或用 -FixSystem'
            if ($script:ExitCode -eq 0) { $script:ExitCode = 5 }
        }
    }

    # ---- 6.3 VC++ 运行库 ----
    $vcNeed  = @('msvcp140.dll', 'vcruntime140.dll', 'vcruntime140_1.dll')
    $vcFound = 0
    foreach ($dll in $vcNeed) {
        if (Test-Path -LiteralPath (Join-Path $env:WINDIR ('System32\' + $dll))) { $vcFound++ }
    }
    $vcInPySide = $false
    $psDirProbe = Invoke-Py -ArgList @('-c', 'import PySide6,os;print(os.path.dirname(PySide6.__file__))')
    if ($psDirProbe.Code -eq 0) {
        $psDir = (@($psDirProbe.Text -split "`r?`n")[0]).Trim()
        if ($psDir) {
            Write-Log ('PySide6 目录: {0}' -f $psDir) 'INFO'
            if (Test-Path -LiteralPath (Join-Path $psDir 'msvcp140.dll')) { $vcInPySide = $true }
        }
    }
    if ($vcFound -eq $vcNeed.Count) {
        Register-Check 'VC++ 2015-2022 运行库' 'OK' '系统 System32 里 3 个 DLL 齐全'
    } elseif ($vcInPySide) {
        Register-Check 'VC++ 2015-2022 运行库' 'OK' '系统未装，但 PySide6 目录自带 msvcp140/vcruntime140，够用'
    } else {
        $fixed = $false
        if ($FixSystem) { $fixed = Install-VCRedist }
        if ($fixed) {
            Register-Check 'VC++ 2015-2022 运行库' 'OK' '已通过 -FixSystem 安装'
        } else {
            Register-Check 'VC++ 2015-2022 运行库' 'WARN' '未检测到；若启动报"找不到 vcruntime140.dll"，装 https://aka.ms/vs/17/release/vc_redist.x64.exe'
        }
    }

    # ---- 6.4 字体 ----
    $fontMiss = New-Object System.Collections.ArrayList
    foreach ($f in @('msyh.ttc', 'msyhbd.ttc', 'seguiemj.ttf')) {
        if (-not (Test-Path -LiteralPath (Join-Path $env:WINDIR ('Fonts\' + $f)))) { [void]$fontMiss.Add($f) }
    }
    if ($fontMiss.Count -eq 0) {
        Register-Check '中文字体' 'OK' 'Microsoft YaHei / Segoe UI Emoji 齐全（src\theme.py:502,1024）'
    } else {
        Register-Check '中文字体' 'WARN' ('缺少: {0}（只影响观感，程序仍能启动）' -f ($fontMiss -join ', '))
    }

    # ---- 6.5 data 目录写权限 ----
    $dataDir  = Join-Path $ProjectRoot 'data'
    $testFile = Join-Path $dataDir ('.write_test_{0}.tmp' -f $PID)
    try {
        Set-Content -LiteralPath $testFile -Value 'ok' -Encoding ASCII -ErrorAction Stop
        Remove-Item -LiteralPath $testFile -Force -ErrorAction SilentlyContinue
        Register-Check 'data 目录写权限' 'OK' $dataDir
    } catch {
        Register-Check 'data 目录写权限' 'FAIL' ('无法写入 {0}: {1}' -f $dataDir, $_.Exception.Message)
    }

    # ---- 6.6 数据库文件 ----
    $dbFile = Join-Path $dataDir 'galgame.db'
    if (Test-Path -LiteralPath $dbFile) { Register-Check 'SQLite 数据库文件' 'OK' $dbFile }
    else { Register-Check 'SQLite 数据库文件' 'WARN' '尚未创建（首次运行会自动建表，属正常）' }

    # ---- 6.7 CG 根目录（只读 settings.json，不修改）----
    $settingsPath = Join-Path $dataDir 'settings.json'
    if (Test-Path -LiteralPath $settingsPath) {
        try {
            $st = (Get-Content -LiteralPath $settingsPath -Raw -Encoding UTF8 | ConvertFrom-Json)
            $cgRoot = [string]$st.cg_root
            if (-not $cgRoot) { $cgRoot = 'E:\cg存储' }
            if (Test-Path -LiteralPath $cgRoot) {
                Register-Check 'CG 根目录' 'OK' $cgRoot
            } else {
                Register-Check 'CG 根目录' 'WARN' ('{0} 不存在；截图/本地 CG 会受影响，可在程序「设置」里改名' -f $cgRoot)
            }
        } catch {
            Register-Check 'CG 根目录' 'WARN' 'settings.json 解析失败（不影响启动，程序会重建默认设置）'
        }
    }

    # ---- 6.8 网络（只有联网功能需要）----
    # 注意: $netOk 只在"确实连上"时才置真，不要写成无条件赋值。
    $netOk = $false
    foreach ($h in @('api.bgm.tv', 'api.vndb.org')) {
        try {
            $tcp = New-Object System.Net.Sockets.TcpClient
            $iar = $tcp.BeginConnect($h, 443, $null, $null)
            if ($iar.AsyncWaitHandle.WaitOne(6000, $false)) {
                try { $tcp.EndConnect($iar) } catch { }
                if ($tcp.Connected) { $netOk = $true }
            }
            $tcp.Close()
            if ($netOk) { break }
        } catch { }
    }
    if ($netOk) {
        Register-Check '网络连通性' 'OK' 'Bangumi/VNDB 可达（封面下载 / 识图 / 随机 CG 可用）'
    } else {
        Register-Check '网络连通性' 'WARN' '外网请求失败；离线仍可管理本地库，联网功能需要网络或代理'
    }
}

# ==============================================================================
# 步骤 7: 端到端离线校验
# ==============================================================================
Write-Step '端到端离线校验（导入全部源码模块 + Qt 平台插件 + 数据库可读）'

$stampFile = (Get-Date).ToString('yyyyMMddHHmmss')
$verifyOut = Join-Path $env:TEMP ('galgame_verify_{0}.txt' -f $stampFile)
$driver    = Join-Path $env:TEMP ('galgame_verify_{0}.py'  -f $stampFile)
$env:GM_VERIFY_OUT = $verifyOut

$driverCode = @'
# -*- coding: utf-8 -*-
"""Galgame Memoir 环境校验（由 setup_env.ps1 生成，跑完即删，不属于项目源码）"""
import os, sys, sqlite3

ROOT = r"__ROOT__"
OUT  = os.environ.get("GM_VERIFY_OUT", os.path.join(os.environ.get("TEMP", "."), "gm_verify.txt"))
sys.path.insert(0, os.path.join(ROOT, "src"))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

lines = []
def rep(state, tag, detail=""):
    d = str(detail).replace("|", "/").replace("\r", " ").replace("\n", " ").strip()
    lines.append("%s|%s|%s" % (state, tag, d))
    print("%s | %s | %s" % (state, tag, d))

MODS = ["config", "cg_library", "database", "net", "workers", "theme_defs",
        "theme", "theme_manager", "welcome", "widgets", "dialogs",
        "random_cg_api", "random_cg_viewer"]

fails = 0

# 1) 第三方包
try:
    import PySide6, requests, PIL
    rep("OK", "python_pkgs", "PySide6=%s requests=%s pillow=%s" % (
        getattr(PySide6, "__version__", "?"),
        getattr(requests, "__version__", "?"),
        getattr(PIL, "__version__", "?")))
except Exception as e:
    fails += 1
    rep("FAIL", "python_pkgs", "%s: %s" % (type(e).__name__, e))

# 2) Qt 平台插件（真实启动用 qwindows.dll，离屏校验用 qoffscreen.dll）
try:
    from PySide6.QtCore import QLibraryInfo
    plugins = QLibraryInfo.path(QLibraryInfo.LibraryPath.PluginsPath)
    qw = os.path.join(plugins, "platforms", "qwindows.dll")
    qo = os.path.join(plugins, "platforms", "qoffscreen.dll")
    if os.path.isfile(qw):
        rep("OK", "qwindows_plugin", qw)
    else:
        fails += 1
        rep("FAIL", "qwindows_plugin", "missing " + qw)
    if os.path.isfile(qo):
        rep("OK", "qoffscreen_plugin", qo)
    else:
        fails += 1
        rep("FAIL", "qoffscreen_plugin", "missing " + qo)
except Exception as e:
    fails += 1
    rep("FAIL", "qt_plugins", "%s: %s" % (type(e).__name__, e))

# 3) QApplication（离屏）
try:
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication([])
    rep("OK", "QApplication", "platform=" + app.platformName())
except Exception as e:
    fails += 1
    rep("FAIL", "QApplication", "%s: %s" % (type(e).__name__, e))

# 4) 业务模块逐个导入
for m in MODS:
    try:
        __import__(m)
        rep("OK", "import:" + m)
    except Exception as e:
        fails += 1
        rep("FAIL", "import:" + m, "%s: %s" % (type(e).__name__, e))

# 5) 数据库可读（只读模式，绝不写入）
try:
    db = os.path.join(ROOT, "data", "galgame.db")
    if os.path.isfile(db):
        con = sqlite3.connect("file:%s?mode=ro" % db.replace("\\", "/"), uri=True)
        n = con.execute("select count(*) from sqlite_master").fetchone()[0]
        con.close()
        rep("OK", "sqlite_read", "%d schema objects" % n)
    else:
        rep("OK", "sqlite_read", "db not created yet (first run creates it)")
except Exception as e:
    fails += 1
    rep("FAIL", "sqlite_read", "%s: %s" % (type(e).__name__, e))

# 6) AVIF 解码（随机 CG 用，缺了不致命）
try:
    from PIL import features
    ok = bool(features.check("avif"))
    rep("OK" if ok else "WARN", "avif_decode",
        "Pillow %s avif=%s (AVIF needs Pillow>=11.3)" % (getattr(PIL, "__version__", "?"), ok))
except Exception as e:
    rep("WARN", "avif_decode", str(e))

try:
    with open(OUT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
except Exception as e:
    print("write result failed:", e)

sys.exit(1 if fails else 0)
'@
$driverCode = $driverCode.Replace('__ROOT__', $ProjectRoot)

$driverWritten = $true
try {
    [System.IO.File]::WriteAllText($driver, $driverCode, (New-Object System.Text.UTF8Encoding($false)))
} catch {
    $driverWritten = $false
    Register-Check '生成校验脚本' 'FAIL' $_.Exception.Message
}

if ($driverWritten) {
    $env:PYTHONIOENCODING = 'utf-8'
    $null = Invoke-Py -ArgList @($driver)

    $checkLines = @()
    if (Test-Path -LiteralPath $verifyOut) {
        $checkLines = @(Get-Content -LiteralPath $verifyOut -Encoding UTF8 | Where-Object { $_.Trim() -ne '' })
    }
    if ($checkLines.Count -eq 0) {
        Register-Check '端到端离线校验' 'FAIL' '校验脚本没有产出结果，请手动跑: python "src\main.py"'
    } else {
        foreach ($ln in $checkLines) {
            $parts = $ln.Split('|')
            if ($parts.Count -ge 2) {
                $st  = $parts[0].Trim()
                $tag = $parts[1].Trim()
                $det = ''
                if ($parts.Count -ge 3) { $det = $parts[2].Trim() }
                if ($st -eq 'OK')   { Register-Check $tag 'OK' $det }
                if ($st -eq 'WARN') { Register-Check $tag 'WARN' $det }
                if ($st -eq 'FAIL') { Register-Check $tag 'FAIL' $det }
            }
        }
    }
    Remove-Item -LiteralPath $driver, $verifyOut -Force -ErrorAction SilentlyContinue
    Remove-Item Env:\GM_VERIFY_OUT -ErrorAction SilentlyContinue
}

$exePath = Join-Path $ProjectRoot 'Galgame Manager.exe'
if (Test-Path -LiteralPath $exePath) {
    $sz = (Get-Item -LiteralPath $exePath).Length
    if ($sz -gt 10000) { Register-Check '启动器 Galgame Manager.exe' 'OK' ('{0} bytes' -f $sz) }
    else { Register-Check '启动器 Galgame Manager.exe' 'WARN' '文件异常小，可能损坏；可用 launcher\build_exe.bat 重编译' }
}

# ==============================================================================
# 步骤 8: 结果汇总
# ==============================================================================
Write-Host ''
Write-Host '====================================================================' -ForegroundColor DarkCyan
Write-Host ' 结果汇总' -ForegroundColor Cyan
Write-Host '====================================================================' -ForegroundColor DarkCyan
$okCount = 0; $warnCount = 0; $failCount = 0
foreach ($c in $script:Checks) {
    $mark = '[ OK ]'; $col = 'Green'
    if ($c.State -eq 'WARN') { $mark = '[WARN]'; $col = 'Yellow'; $warnCount++ }
    if ($c.State -eq 'FAIL') { $mark = '[FAIL]'; $col = 'Red';    $failCount++ }
    if ($c.State -eq 'OK')   { $okCount++ }
    $det = ''
    if ($c.Detail) { $det = '  ' + $c.Detail }
    Write-Host (' {0} {1}{2}' -f $mark, $c.Name, $det) -ForegroundColor $col
}
Write-Host ''
Write-Host (' 通过 {0} 项 / 警告 {1} 项 / 未通过 {2} 项' -f $okCount, $warnCount, $failCount) -ForegroundColor White
Write-Host (' 日志: {0}' -f $LogFile) -ForegroundColor Gray
Write-Log ('通过 {0} 项 / 警告 {1} 项 / 未通过 {2} 项' -f $okCount, $warnCount, $failCount) 'INFO'

if ($failCount -gt 0) {
    Write-Host ''
    Write-Host ' 结论: 环境【尚未就绪】。请看上面 [FAIL] 项的处理建议，处理后重跑本脚本。' -ForegroundColor Red
    Write-Log '结论: 环境尚未就绪，请按上面 [FAIL] 项的处理建议处理后重跑本脚本。' 'ERROR'
    if ($script:ExitCode -eq 0) { $script:ExitCode = 4 }
} else {
    Write-Host ''
    Write-Host ' 结论: 非 Python 环境已就绪 —— 可以双击 Galgame Manager.exe 启动，' -ForegroundColor Green
    Write-Host '       也可以运行 repair\repair.bat 或 python src\main.py。' -ForegroundColor Green
    Write-Log '结论: 非 Python 环境已就绪，可以启动 Galgame Manager 了。' 'OK'

    if ($Launch) {
        Write-Step '启动程序（Galgame Memoir）'
        $runner = $script:Py
        $pyw2 = Join-Path (Split-Path -Parent $script:Py) 'pythonw.exe'
        if (Test-Path -LiteralPath $pyw2) { $runner = $pyw2 }
        try {
            $mainPy = Join-Path $ProjectRoot 'src\main.py'
            Start-Process -FilePath $runner -ArgumentList ('"' + $mainPy + '"') -WorkingDirectory $ProjectRoot | Out-Null
            Register-Check '启动程序' 'OK' ('已用 {0} 拉起 src\main.py（窗口标题应为 Galgame Memoir）' -f (Split-Path -Leaf $runner))
        } catch {
            Register-Check '启动程序' 'FAIL' $_.Exception.Message
            $script:ExitCode = 4
        }
    }
}

Write-Host ''
Write-Log ('脚本结束，退出码 {0}' -f $script:ExitCode) 'INFO'
exit $script:ExitCode
