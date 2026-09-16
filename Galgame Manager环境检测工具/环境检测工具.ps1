#Requires -Version 5.1
<#
================================================================================
 Galgame Manager 环境检测工具（图形界面）  v1.2
 文件名: 环境检测工具.ps1        编码: UTF-8 with BOM
 位置  : 可以放在项目根目录，也可以放在子目录里（会自动向上找项目根目录）
 依赖  : setup_env.ps1（必须与本脚本放在同一目录）
         assets\logo.png 或 assets\app_icon.png（可选，左侧 Logo，在项目根目录里找）
 启动  : 双击同目录的「Galgame Manager环境检测工具.exe」，或
         powershell -NoProfile -ExecutionPolicy Bypass -File ".\环境检测工具.ps1"
--------------------------------------------------------------------------------
 【界面】
   左侧  : Logo + 工具/项目目录 + OK/WARN/FAIL 计数 + 自绘进度环 + 当前最快镜像源
   按钮  :
     ⚡ 一键安装   -> setup_env.ps1（自动测速选最快源 -> 补齐缺失依赖 -> 启动前校验）
     🔍 仅检测     -> setup_env.ps1 -VerifyOnly（只看不改）
     📡 测速       -> setup_env.ps1 -OnlyMirrorTest（只测主站+备用镜像速度）
     ▶ 启动程序   -> 优先 Galgame Manager.exe，没有就用 pythonw 起 src\main.py
     📄 日志 / 📁 项目目录 / 清空
   勾选框: 「完成后自动启动 Galgame Manager」——脚本跑完且退出码为 0 时自动拉起程序
           （状态会记住，下次打开还是你上次的选择）
--------------------------------------------------------------------------------
 【v1.2 变更】
   * 支持把工具放进项目根的子目录：自动向上查找含 src\main.py + data\ 的那一层
   * 线性进度条换成自绘进度环（Path + ArcSegment，零第三方依赖）
   * 新增「完成后自动启动 Galgame Manager」勾选框（记忆状态）
   * 左侧栏改为可滚动，窗口压到最小高度也不会切掉内容
================================================================================
#>

Add-Type -AssemblyName PresentationFramework
Add-Type -AssemblyName PresentationCore
Add-Type -AssemblyName WindowsBase

# ==============================================================================
# 路径解析
# ==============================================================================
$ScriptPath = $PSCommandPath
if (-not $ScriptPath) { $ScriptPath = $MyInvocation.MyCommand.Path }
$ScriptRoot  = Split-Path -Parent $ScriptPath
$SetupScript = Join-Path $ScriptRoot 'setup_env.ps1'

function Resolve-GMProjectRoot {
    # 工具可能放在 <项目根>\xxx\ 里，所以从 $StartDir 向上找"同时含 src\main.py 与 data\"的那一层
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

$ProjectRoot = Resolve-GMProjectRoot -StartDir $ScriptRoot
$RootOk = $true
if (-not $ProjectRoot) {
    $ProjectRoot = $ScriptRoot
    $RootOk = $false
}

if (-not (Test-Path -LiteralPath $SetupScript)) {
    [System.Windows.MessageBox]::Show(
        ("找不到 setup_env.ps1。`n请确保它和本脚本在同一目录：`n{0}" -f $ScriptRoot),
        '缺少文件', 'OK', 'Error') | Out-Null
    exit 1
}

$LogDir = Join-Path $env:TEMP 'GalgameManagerGUI'
if (-not (Test-Path -LiteralPath $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}
$PrefsFile = Join-Path $LogDir 'gui_prefs.json'

# ==============================================================================
# XAML 界面
# ==============================================================================
[xml]$Xaml = @'
<Window xmlns="http://schemas.microsoft.com/winfx/2006/xaml/presentation"
        xmlns:x="http://schemas.microsoft.com/winfx/2006/xaml"
        Title="Galgame Manager 环境检测工具"
        Height="780" Width="1160"
        MinHeight="620" MinWidth="940"
        WindowStartupLocation="CenterScreen"
        Background="#FF1E1E2E"
        FontFamily="Microsoft YaHei UI, Segoe UI"
        UseLayoutRounding="True"
        SnapsToDevicePixels="True">
  <Window.Resources>
    <Style x:Key="FlatButton" TargetType="Button">
      <Setter Property="Background" Value="#FF313244"/>
      <Setter Property="Foreground" Value="#FFCDD6F4"/>
      <Setter Property="BorderThickness" Value="0"/>
      <Setter Property="Padding" Value="15,9"/>
      <Setter Property="Margin" Value="0,0,9,9"/>
      <Setter Property="FontSize" Value="13"/>
      <Setter Property="Cursor" Value="Hand"/>
      <Setter Property="Template">
        <Setter.Value>
          <ControlTemplate TargetType="Button">
            <Border x:Name="Bd" Background="{TemplateBinding Background}"
                    CornerRadius="6" Padding="{TemplateBinding Padding}">
              <ContentPresenter HorizontalAlignment="Center" VerticalAlignment="Center"/>
            </Border>
            <ControlTemplate.Triggers>
              <Trigger Property="IsMouseOver" Value="True">
                <Setter TargetName="Bd" Property="Background" Value="#FF45475A"/>
              </Trigger>
              <Trigger Property="IsEnabled" Value="False">
                <Setter Property="Opacity" Value="0.4"/>
              </Trigger>
            </ControlTemplate.Triggers>
          </ControlTemplate>
        </Setter.Value>
      </Setter>
    </Style>
    <Style x:Key="PrimaryButton" TargetType="Button" BasedOn="{StaticResource FlatButton}">
      <Setter Property="Background" Value="#FF89B4FA"/>
      <Setter Property="Foreground" Value="#FF11111B"/>
      <Setter Property="FontWeight" Value="SemiBold"/>
    </Style>
    <Style x:Key="Caption" TargetType="TextBlock">
      <Setter Property="FontSize" Value="11"/>
      <Setter Property="Foreground" Value="#FF6C7086"/>
    </Style>
    
  </Window.Resources>

  <Grid>
    <Grid.ColumnDefinitions>
      <ColumnDefinition Width="256"/>
      <ColumnDefinition Width="*"/>
    </Grid.ColumnDefinitions>

    <!-- ===================== 左侧栏 ===================== -->
    <Border Grid.Column="0" Background="#FF181825">
      <ScrollViewer VerticalScrollBarVisibility="Auto" HorizontalScrollBarVisibility="Disabled">
        <StackPanel Margin="24,24,24,20">

          <!-- Logo -->
          <Border Width="150" Height="150" CornerRadius="18"
                  Background="#FF313244" HorizontalAlignment="Center">
            <Grid>
              <Image x:Name="ImgLogo" Stretch="Uniform" Margin="10"/>
              <TextBlock x:Name="TxtLogoPlaceholder" Text="GM"
                         FontSize="54" FontWeight="Bold"
                         Foreground="#FF89B4FA"
                         HorizontalAlignment="Center" VerticalAlignment="Center"
                         Visibility="Collapsed"/>
            </Grid>
          </Border>

          <TextBlock Text="Galgame Manager" FontSize="16" FontWeight="Bold"
                     Foreground="#FFCDD6F4" HorizontalAlignment="Center"
                     Margin="0,16,0,2"/>
          <TextBlock Text="环境检测工具" FontSize="13"
                     Foreground="#FFA6ADC8" HorizontalAlignment="Center"/>
          <TextBlock Text="v1.2" FontSize="11"
                     Foreground="#FF6C7086" HorizontalAlignment="Center"
                     Margin="0,4,0,0"/>

          <Border Height="1" Background="#FF313244" Margin="0,16,0,14"/>

          <TextBlock Text="项目目录" Style="{StaticResource Caption}"/>
          <TextBlock x:Name="TxtProject" Text="..."
                     FontSize="11" Foreground="#FFA6ADC8"
                     TextWrapping="Wrap" Margin="0,4,0,0"/>
          <TextBlock Text="工具目录" Style="{StaticResource Caption}" Margin="0,10,0,0"/>
          <TextBlock x:Name="TxtTool" Text="..."
                     FontSize="11" Foreground="#FF6C7086"
                     TextWrapping="Wrap" Margin="0,4,0,0"/>

          <Border Height="1" Background="#FF313244" Margin="0,14,0,14"/>

          <!-- 计数 -->
          <Grid>
            <Grid.ColumnDefinitions>
              <ColumnDefinition Width="*"/>
              <ColumnDefinition Width="*"/>
              <ColumnDefinition Width="*"/>
            </Grid.ColumnDefinitions>
            <StackPanel Grid.Column="0">
              <TextBlock x:Name="TxtOkNum" Text="0" FontSize="24" FontWeight="Bold"
                         Foreground="#FFA6E3A1" HorizontalAlignment="Center"/>
              <TextBlock Text="OK" FontSize="10" Foreground="#FF6C7086"
                         HorizontalAlignment="Center" Margin="0,2,0,0"/>
            </StackPanel>
            <StackPanel Grid.Column="1">
              <TextBlock x:Name="TxtWarnNum" Text="0" FontSize="24" FontWeight="Bold"
                         Foreground="#FFF9E2AF" HorizontalAlignment="Center"/>
              <TextBlock Text="WARN" FontSize="10" Foreground="#FF6C7086"
                         HorizontalAlignment="Center" Margin="0,2,0,0"/>
            </StackPanel>
            <StackPanel Grid.Column="2">
              <TextBlock x:Name="TxtFailNum" Text="0" FontSize="24" FontWeight="Bold"
                         Foreground="#FFF38BA8" HorizontalAlignment="Center"/>
              <TextBlock Text="FAIL" FontSize="10" Foreground="#FF6C7086"
                         HorizontalAlignment="Center" Margin="0,2,0,0"/>
            </StackPanel>
          </Grid>

          <Border Height="1" Background="#FF313244" Margin="0,14,0,14"/>

          <!-- 自绘进度环：背景圆环 + 由代码生成 ArcSegment 的进度弧 -->
          <Grid Width="136" Height="136" HorizontalAlignment="Center">
            <Ellipse Width="112" Height="112" Stroke="#FF313244" StrokeThickness="11"
                     HorizontalAlignment="Center" VerticalAlignment="Center"/>
            <Path x:Name="RingArc" Stroke="#FF89B4FA" StrokeThickness="11"
                  StrokeStartLineCap="Round" StrokeEndLineCap="Round"/>
            <StackPanel HorizontalAlignment="Center" VerticalAlignment="Center"
                        IsHitTestVisible="False">
              <TextBlock x:Name="TxtRingPct" Text="0%" FontSize="24" FontWeight="Bold"
                         Foreground="#FFCDD6F4" HorizontalAlignment="Center"/>
              <TextBlock x:Name="TxtRingCap" Text="步骤 0/8" FontSize="10"
                         Foreground="#FF6C7086" HorizontalAlignment="Center" Margin="0,2,0,0"/>
            </StackPanel>
          </Grid>

          <Border Height="1" Background="#FF313244" Margin="0,14,0,14"/>

          <TextBlock Text="当前最快镜像源" Style="{StaticResource Caption}"/>
          <TextBlock x:Name="TxtFastest" Text="—" FontSize="12"
                     Foreground="#FF94E2D5" TextWrapping="Wrap" Margin="0,4,0,0"/>
        </StackPanel>
      </ScrollViewer>
    </Border>

    <!-- ===================== 右侧主区 ===================== -->
    <Grid Grid.Column="1" Margin="20,20,20,16">
      <Grid.RowDefinitions>
        <RowDefinition Height="Auto"/>
        <RowDefinition Height="Auto"/>
        <RowDefinition Height="*"/>
        <RowDefinition Height="Auto"/>
      </Grid.RowDefinitions>

      <WrapPanel Grid.Row="0" Margin="0,0,0,6">
        <Button x:Name="BtnInstall"    Content="⚡  一键安装" ToolTip="自动测速选最快的镜像源，补齐缺失依赖并校验" Style="{StaticResource PrimaryButton}"/>
        <Button x:Name="BtnVerify"     Content="🔍  仅检测"   ToolTip="只检测、不安装任何东西（-VerifyOnly）"          Style="{StaticResource FlatButton}"/>
        <Button x:Name="BtnSpeedTest"  Content="📡  测速"     ToolTip="只测主站与备用镜像的响应速度（-OnlyMirrorTest）" Style="{StaticResource FlatButton}"/>
        <Button x:Name="BtnLaunch"     Content="▶  启动程序"  ToolTip="启动 Galgame Manager"                            Style="{StaticResource FlatButton}"/>
        <Button x:Name="BtnOpenLog"    Content="📄  日志"     ToolTip="打开最近一次运行的日志文件"                      Style="{StaticResource FlatButton}"/>
        <Button x:Name="BtnOpenFolder" Content="📁  项目目录" ToolTip="在资源管理器中打开项目根目录"                    Style="{StaticResource FlatButton}"/>
        <Button x:Name="BtnClear"      Content="清空"         ToolTip="只清空日志显示区"                                Style="{StaticResource FlatButton}"/>
      </WrapPanel>

      <StackPanel Grid.Row="1" Margin="2,0,0,10">
        <Border x:Name="ChkRow" Background="Transparent" Cursor="Hand"
                Padding="0,4,12,4" HorizontalAlignment="Left"
                ToolTip="脚本跑完且退出码为 0 时，自动帮你把程序启动起来">
          <StackPanel Orientation="Horizontal">
            <Border x:Name="ChkBox" Width="17" Height="17" CornerRadius="4"
                    Background="#FF313244" BorderBrush="#FF6C7086" BorderThickness="1.5"
                    VerticalAlignment="Center">
              <TextBlock x:Name="ChkTick" Text="✓" FontSize="11" FontWeight="Bold"
                         Foreground="#FF11111B"
                         HorizontalAlignment="Center" VerticalAlignment="Center"
                         Visibility="Collapsed"/>
            </Border>
            <TextBlock x:Name="ChkText" Text="完成后自动启动 Galgame Manager"
                       Margin="8,0,0,0" VerticalAlignment="Center"
                       FontSize="12" Foreground="#FFA6ADC8"/>
          </StackPanel>
        </Border>
      </StackPanel>

      <Border Grid.Row="2" Background="#FF181825" CornerRadius="8"
              Padding="4" Margin="0,0,0,10">
        <RichTextBox x:Name="RtbLog" Background="Transparent"
                     BorderThickness="0" Foreground="#FFCDD6F4"
                     IsReadOnly="True" IsDocumentEnabled="False"
                     FontFamily="Cascadia Mono, Consolas, Microsoft YaHei UI"
                     FontSize="12" VerticalScrollBarVisibility="Auto"
                     Padding="12,10"/>
      </Border>

      <TextBlock Grid.Row="3" x:Name="TxtStatus" Text="就绪"
                 Foreground="#FFA6ADC8" FontSize="12"/>
    </Grid>
  </Grid>
</Window>
'@

$Reader = New-Object System.Xml.XmlNodeReader $Xaml
$Window = [Windows.Markup.XamlReader]::Load($Reader)

# ---- 窗口图标（在项目根目录找）----
$iconPath = Join-Path $ProjectRoot 'assets\app_icon.ico'
if (Test-Path -LiteralPath $iconPath) {
    try { $Window.Icon = New-Object System.Windows.Media.Imaging.BitmapImage ([Uri]$iconPath) } catch { }
}

# ---- 控件引用 ----
$TxtProject    = $Window.FindName('TxtProject')
$TxtTool       = $Window.FindName('TxtTool')
$TxtStatus     = $Window.FindName('TxtStatus')
$TxtOkNum      = $Window.FindName('TxtOkNum')
$TxtWarnNum    = $Window.FindName('TxtWarnNum')
$TxtFailNum    = $Window.FindName('TxtFailNum')
$TxtFastest    = $Window.FindName('TxtFastest')
$TxtRingPct    = $Window.FindName('TxtRingPct')
$TxtRingCap    = $Window.FindName('TxtRingCap')
$RingArc       = $Window.FindName('RingArc')
$ImgLogo       = $Window.FindName('ImgLogo')
$TxtLogoPh     = $Window.FindName('TxtLogoPlaceholder')
$ChkRow        = $Window.FindName('ChkRow')
$ChkBox        = $Window.FindName('ChkBox')
$ChkTick       = $Window.FindName('ChkTick')
$ChkText       = $Window.FindName('ChkText')
$BtnInstall    = $Window.FindName('BtnInstall')
$BtnVerify     = $Window.FindName('BtnVerify')
$BtnSpeedTest  = $Window.FindName('BtnSpeedTest')
$BtnLaunch     = $Window.FindName('BtnLaunch')
$BtnOpenLog    = $Window.FindName('BtnOpenLog')
$BtnOpenFolder = $Window.FindName('BtnOpenFolder')
$BtnClear      = $Window.FindName('BtnClear')
$RtbLog        = $Window.FindName('RtbLog')

$TxtProject.Text = $ProjectRoot
$TxtTool.Text    = $ScriptRoot

# ---- 左侧 Logo：按顺序找，找到哪个用哪个 ----
$logoCandidates = @(
    (Join-Path $ProjectRoot 'assets\logo.png'),      # 推荐：正方形透明 PNG
    (Join-Path $ProjectRoot 'assets\app_icon.png'),  # 本项目自带
    (Join-Path $ProjectRoot 'assets\app_icon.ico'),
    (Join-Path $ProjectRoot 'assets\icon.ico'),
    (Join-Path $ProjectRoot 'logo.png')
)
$logoLoaded = $false
foreach ($p in $logoCandidates) {
    if (Test-Path -LiteralPath $p) {
        try {
            $bmp = New-Object System.Windows.Media.Imaging.BitmapImage
            $bmp.BeginInit()
            $bmp.CacheOption      = [System.Windows.Media.Imaging.BitmapCacheOption]::OnLoad
            $bmp.DecodePixelWidth = 300          # 150px 框 @2x，避免每次解码 1.8MB 原图
            $bmp.UriSource        = New-Object System.Uri($p)
            $bmp.EndInit()
            $bmp.Freeze()
            $ImgLogo.Source = $bmp
            $logoLoaded = $true
            break
        } catch { }
    }
}
if (-not $logoLoaded) {
    $ImgLogo.Visibility = 'Collapsed'
    $TxtLogoPh.Visibility = 'Visible'
}

# ==============================================================================
# 运行状态
# ==============================================================================
$script:LogOffset     = 0
$script:LogRemainder  = ''
$script:OkCount       = 0
$script:WarnCount     = 0
$script:FailCount     = 0
$script:StepCount     = 0
$script:TotalSteps    = 8
$script:CountsLocked  = $false
$script:CurrentLog    = ''
$script:Proc          = $null
$script:Timer         = $null
$script:Running       = $false
$script:Mode          = 'Install'
$script:AutoLaunch    = $true

function Convert-HexToBrush {
    param([string]$Hex)
    $Hex = $Hex -replace '^#', ''
    if ($Hex.Length -eq 8) {
        $a = [Convert]::ToByte($Hex.Substring(0,2),16)
        $r = [Convert]::ToByte($Hex.Substring(2,2),16)
        $g = [Convert]::ToByte($Hex.Substring(4,2),16)
        $b = [Convert]::ToByte($Hex.Substring(6,2),16)
        return New-Object System.Windows.Media.SolidColorBrush(
            [System.Windows.Media.Color]::FromArgb($a,$r,$g,$b))
    }
    return [System.Windows.Media.Brushes]::White
}

function Update-AutoLaunchVisual {
    # 勾选框外观完全由代码控制：避免 ControlTemplate.Triggers 的 Setter
    # 被模板内元素上的本地值（Background="..."）压过去，导致"永远蓝色"。
    if ($script:AutoLaunch) {
        $ChkBox.Background  = Convert-HexToBrush '#FF89B4FA'
        $ChkBox.BorderBrush = Convert-HexToBrush '#FF89B4FA'
        $ChkTick.Visibility = 'Visible'
    } else {
        $ChkBox.Background  = Convert-HexToBrush '#FF313244'
        $ChkBox.BorderBrush = Convert-HexToBrush '#FF6C7086'
        $ChkTick.Visibility = 'Collapsed'
    }
}

function Set-Status {
    param([string]$Text, [string]$Hex = '#FFA6ADC8')
    $TxtStatus.Text = $Text
    $TxtStatus.Foreground = Convert-HexToBrush $Hex
}

function Update-ProgressRing {
    # 自绘进度环：用 PathGeometry + ArcSegment 画一段圆弧，从 12 点方向顺时针
    param([double] $Percent)
    $p = [Math]::Max(0.0, [Math]::Min(100.0, $Percent))
    $TxtRingPct.Text = ('{0:N0}%' -f $p)
    if ($p -le 0.01) { $RingArc.Data = $null; return }

    $cx  = 68.0; $cy = 68.0; $r = 56.0
    $sweep = 360.0 * $p / 100.0
    if ($sweep -ge 359.99) { $sweep = 359.99 }      # 100% 时画整圈（起点=终点画不出弧）
    $rad  = [Math]::PI / 180.0
    $a0   = -90.0
    $a1   = $a0 + $sweep
    $sx   = $cx + $r * [Math]::Cos($a0 * $rad)
    $sy   = $cy + $r * [Math]::Sin($a0 * $rad)
    $ex   = $cx + $r * [Math]::Cos($a1 * $rad)
    $ey   = $cy + $r * [Math]::Sin($a1 * $rad)

    $fig = New-Object System.Windows.Media.PathFigure
    $fig.StartPoint = New-Object System.Windows.Point($sx, $sy)
    $arc = New-Object System.Windows.Media.ArcSegment
    $arc.Point          = New-Object System.Windows.Point($ex, $ey)
    $arc.Size           = New-Object System.Windows.Size($r, $r)
    $arc.IsLargeArc     = ($sweep -gt 180.0)
    $arc.SweepDirection = [System.Windows.Media.SweepDirection]::Clockwise
    $null = $fig.Segments.Add($arc)

    $geo = New-Object System.Windows.Media.PathGeometry
    $null = $geo.Figures.Add($fig)
    $RingArc.Data = $geo
}

function Add-LogLine {
    param([string]$Line)

    # 优先采用 setup_env.ps1 汇总行里的精确数字（避免"安装成功"等 OK 行也计数）
    if ($Line -match '通过\s+(\d+)\s*项\s*/\s*警告\s+(\d+)\s*项\s*/\s*未通过\s+(\d+)\s*项') {
        $script:OkCount      = [int]$Matches[1]
        $script:WarnCount    = [int]$Matches[2]
        $script:FailCount    = [int]$Matches[3]
        $script:CountsLocked = $true
    } elseif (-not $script:CountsLocked) {
        if     ($Line -match '\[ OK \]') { $script:OkCount++ }
        elseif ($Line -match '\[WARN\]') { $script:WarnCount++ }
        elseif ($Line -match '\[FAIL\]') { $script:FailCount++ }
    }
    if ($Line -match '\[STEP\]') {
        $script:StepCount++
        $TxtRingCap.Text = ('步骤 {0}/{1}' -f $script:StepCount, $script:TotalSteps)
        Update-ProgressRing ([Math]::Min(95.0, $script:StepCount * 100.0 / $script:TotalSteps))
    }
    if ($Line -match '最快源:\s*(.+?)\s*\((\d+)\s*ms\)') {
        $TxtFastest.Text = ('{0}  ({1} ms)' -f $Matches[1], $Matches[2])
    }

    $TxtOkNum.Text   = [string]$script:OkCount
    $TxtWarnNum.Text = [string]$script:WarnCount
    $TxtFailNum.Text = [string]$script:FailCount

    $hex = '#FFCDD6F4'
    if     ($Line -match '\[ OK \]')  { $hex = '#FFA6E3A1' }
    elseif ($Line -match '\[WARN\]')  { $hex = '#FFF9E2AF' }
    elseif ($Line -match '\[FAIL\]')  { $hex = '#FFF38BA8' }
    elseif ($Line -match '\[STEP\]')  { $hex = '#FF94E2D5' }
    elseif ($Line -match '\[====\]')  { $hex = '#FF89B4FA' }
    elseif ($Line -match '\[INFO\]')  { $hex = '#FFB4BEFE' }

    $para = New-Object System.Windows.Documents.Paragraph
    $para.Margin = New-Object System.Windows.Thickness(0,1,0,1)
    $run = New-Object System.Windows.Documents.Run($Line)
    $run.Foreground = Convert-HexToBrush $hex
    $para.Inlines.Add($run)
    $RtbLog.Document.Blocks.Add($para)

    while ($RtbLog.Document.Blocks.Count -gt 3000) {
        $RtbLog.Document.Blocks.Remove($RtbLog.Document.Blocks.FirstBlock)
    }
    $RtbLog.ScrollToEnd()
}

function Read-LogOnce {
    $path = $script:CurrentLog
    if (-not $path -or -not (Test-Path -LiteralPath $path)) { return }
    $fs = $null
    try {
        $fs = [System.IO.File]::Open($path, 'Open', 'Read', 'ReadWrite')
        if ($fs.Length -le $script:LogOffset) { $fs.Close(); return }
        $fs.Seek($script:LogOffset, 'Begin') | Out-Null
        $sr = New-Object System.IO.StreamReader($fs, [System.Text.Encoding]::UTF8, $true)
        $text = $sr.ReadToEnd()
        $script:LogOffset = $fs.Length
        $sr.Close(); $fs.Close(); $fs = $null

        # 只处理"完整行"，最后一段不完整的留到下一次
        $text  = $script:LogRemainder + $text
        $parts = $text -split "`r?`n"
        $script:LogRemainder = $parts[$parts.Count - 1]
        for ($i = 0; $i -lt $parts.Count - 1; $i++) {
            if ($parts[$i].Trim() -ne '') { Add-LogLine $parts[$i] }
        }
    } catch {
        if ($fs) { try { $fs.Close() } catch { } }
    }
}

function Start-GMApp {
    # 优先用 exe 启动器，其次用 pythonw/python 跑 src\main.py；返回实际用的程序名或 $null
    if (-not $RootOk) { return $null }
    $exe = Join-Path $ProjectRoot 'Galgame Manager.exe'
    if (Test-Path -LiteralPath $exe) {
        try {
            Start-Process -FilePath $exe -WorkingDirectory $ProjectRoot | Out-Null
            return 'Galgame Manager.exe'
        } catch { return $null }
    }
    $mainPy = Join-Path $ProjectRoot 'src\main.py'
    foreach ($n in @('pythonw.exe', 'python.exe')) {
        $c = Get-Command $n -ErrorAction SilentlyContinue
        if ($c -and $c.Source -and (Test-Path -LiteralPath $mainPy)) {
            try {
                Start-Process -FilePath $c.Source -ArgumentList ('"{0}"' -f $mainPy) -WorkingDirectory $ProjectRoot | Out-Null
                return (Split-Path -Leaf $c.Source)
            } catch { return $null }
        }
    }
    return $null
}

function Update-FromLog {
    if (-not $script:Proc) { return }
    Read-LogOnce
    if (-not $script:Proc.HasExited) { return }

    Read-LogOnce                                  # 收尾：把剩余日志读完
    if ($script:LogRemainder -and $script:LogRemainder.Trim() -ne '') {
        Add-LogLine $script:LogRemainder
        $script:LogRemainder = ''
    }
    if ($script:Timer) { $script:Timer.Stop() }
    $script:Running = $false
    $BtnInstall.IsEnabled   = $true
    $BtnVerify.IsEnabled    = $true
    $BtnSpeedTest.IsEnabled = $true
    Update-ProgressRing 100

    $exitCode = $script:Proc.ExitCode
    try { $script:Proc.Dispose() } catch { }
    $script:Proc = $null

    # ---- 测速模式 ----
    if ($script:Mode -eq 'MirrorTest') {
        Add-LogLine ''
        Add-LogLine '========== 测速结束 =========='
        if ($TxtFastest.Text -ne '—') {
            Set-Status ('测速完成 · 最快: ' + $TxtFastest.Text) '#FFA6E3A1'
        } else {
            Set-Status '测速完成 · 没有可用镜像' '#FFF38BA8'
        }
        [System.Windows.MessageBox]::Show(
            ("测速完成。`n最快镜像源: {0}`n`n一键安装时会自动使用它。" -f $TxtFastest.Text),
            '测速完成', 'OK', 'Information') | Out-Null
        return
    }

    # ---- 安装 / 检测模式 ----
    $icon = 'Information'
    $autoNote = ''
    if ($exitCode -eq 0 -and $script:FailCount -eq 0) {
        Set-Status '完成 · 环境就绪' '#FFA6E3A1'
        if ($script:AutoLaunch) {
            $used = Start-GMApp
            if ($used) {
                Add-LogLine ('[ OK ] 已自动启动 Galgame Manager（{0}）' -f $used)
                $autoNote = ("`n`n已自动启动 Galgame Manager（{0}）。" -f $used)
            } else {
                Add-LogLine '[WARN] 勾选了自动启动，但没找到 Galgame Manager.exe / pythonw，请手动点「▶ 启动程序」。'
                $autoNote = "`n`n已勾选自动启动，但没找到启动器，请手动点「▶ 启动程序」。"
            }
        }
    } elseif ($exitCode -eq 2) {
        Set-Status '完成 · 未找到可用的 Python' '#FFF38BA8'
        $icon = 'Warning'
    } elseif ($script:FailCount -gt 0) {
        Set-Status ('完成 · 有未通过项（退出码 {0}）' -f $exitCode) '#FFF38BA8'
        $icon = 'Warning'
    } else {
        Set-Status ('完成 · 退出码 {0}' -f $exitCode) '#FFF9E2AF'
        $icon = 'Warning'
    }

    Add-LogLine ''
    Add-LogLine ('========== 执行结束 · 退出码 {0} ==========' -f $exitCode)

    $tip = ''
    if ($exitCode -eq 2) { $tip = "`n`n请先安装 Python 3.9+（项目自带 python安装包\python-3.14.7-amd64.exe），装完重开本工具。" }
    elseif ($exitCode -eq 3) { $tip = "`n`n依赖没有装上，通常是网络问题。可以先用「📡 测速」看看哪个源快。" }
    elseif ($exitCode -eq 4) { $tip = "`n`n校验没通过，请看日志里最后几条 [FAIL]。" }

    $msg = ("通过 {0} 项 / 警告 {1} 项 / 未通过 {2} 项`n退出码: {3}{4}{5}" -f `
            $script:OkCount, $script:WarnCount, $script:FailCount, $exitCode, $tip, $autoNote)
    [System.Windows.MessageBox]::Show($msg, '执行完成', 'OK', $icon) | Out-Null
}

function Start-Setup {
    param([ValidateSet('Install','Verify','MirrorTest')] [string] $Mode = 'Install')

    if ($script:Running) {
        [System.Windows.MessageBox]::Show('已有任务在运行中，请等待完成。', '提示', 'OK', 'Information') | Out-Null
        return
    }
    if (-not $RootOk) {
        [System.Windows.MessageBox]::Show(
            ("没有找到项目根目录（往上找含 src\main.py 与 data\ 的文件夹都没找到）。`n`n当前工具目录: {0}`n`n请把本工具放回 Galgame Manager 项目里再试。" -f $ScriptRoot),
            '找不到项目', 'OK', 'Warning') | Out-Null
        return
    }

    # 重置界面
    $RtbLog.Document.Blocks.Clear()
    $script:LogOffset    = 0
    $script:LogRemainder = ''
    $script:OkCount      = 0
    $script:WarnCount    = 0
    $script:FailCount    = 0
    $script:StepCount    = 0
    $script:CountsLocked = $false
    $script:Mode         = $Mode
    $TxtOkNum.Text = '0'; $TxtWarnNum.Text = '0'; $TxtFailNum.Text = '0'
    $TxtFastest.Text = '—'
    $TxtRingCap.Text = ('步骤 0/{0}' -f $script:TotalSteps)
    Update-ProgressRing 0

    $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
    $script:CurrentLog = Join-Path $LogDir ('{0}_{1}.log' -f $Mode.ToLower(), $stamp)

    # 组装命令行：写死日志路径方便实时读取；项目根目录用解析结果钉住
    $argList = @('-NoProfile', '-ExecutionPolicy', 'Bypass',
                 '-File', ('"{0}"' -f $SetupScript),
                 '-ProjectRoot', ('"{0}"' -f $ProjectRoot),
                 '-LogFile', ('"{0}"' -f $script:CurrentLog))
    switch ($Mode) {
        'Verify'     { $argList += '-VerifyOnly' }
        'MirrorTest' { $argList += '-OnlyMirrorTest' }
    }

    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName        = 'powershell.exe'
    $psi.Arguments       = ($argList -join ' ')
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow  = $true
    $psi.WindowStyle     = 'Hidden'

    $proc = New-Object System.Diagnostics.Process
    $proc.StartInfo = $psi

    try { $null = $proc.Start() }
    catch {
        [System.Windows.MessageBox]::Show(('启动失败: {0}' -f $_.Exception.Message), '错误', 'OK', 'Error') | Out-Null
        return
    }

    $script:Proc    = $proc
    $script:Running = $true
    $BtnInstall.IsEnabled   = $false
    $BtnVerify.IsEnabled    = $false
    $BtnSpeedTest.IsEnabled = $false

    switch ($Mode) {
        'Install'    { Set-Status '安装中...（正在测速选源 + 补齐依赖）' '#FFF9E2AF' }
        'Verify'     { Set-Status '检测中...（不会安装任何东西）'        '#FFF9E2AF' }
        'MirrorTest' { Set-Status '测速中...'                            '#FFF9E2AF' }
    }

    if (-not $script:Timer) {
        $script:Timer = New-Object System.Windows.Threading.DispatcherTimer
        $script:Timer.Interval = [TimeSpan]::FromMilliseconds(250)
        $script:Timer.Add_Tick({ Update-FromLog })
    }
    $script:Timer.Start()
}

# ==============================================================================
# 偏好设置（勾选框状态记忆）
# ==============================================================================
try {
    if (Test-Path -LiteralPath $PrefsFile) {
        $prefs = Get-Content -LiteralPath $PrefsFile -Raw -Encoding UTF8 | ConvertFrom-Json
        if ($null -ne $prefs.autoLaunch) { $script:AutoLaunch = [bool]$prefs.autoLaunch }
    }
} catch { }
Update-AutoLaunchVisual

$ChkRow.Add_MouseLeftButtonUp({
    $script:AutoLaunch = -not $script:AutoLaunch
    Update-AutoLaunchVisual
    try {
        (@{ autoLaunch = $script:AutoLaunch } | ConvertTo-Json) |
            Set-Content -LiteralPath $PrefsFile -Encoding UTF8
    } catch { }
})
$ChkRow.Add_MouseEnter({ $ChkText.Foreground = Convert-HexToBrush '#FFCDD6F4' })
$ChkRow.Add_MouseLeave({ $ChkText.Foreground = Convert-HexToBrush '#FFA6ADC8' })

# ==============================================================================
# 按钮事件
# ==============================================================================
$BtnInstall.Add_Click({   Start-Setup -Mode 'Install' })
$BtnVerify.Add_Click({    Start-Setup -Mode 'Verify' })
$BtnSpeedTest.Add_Click({ Start-Setup -Mode 'MirrorTest' })
$BtnClear.Add_Click({     $RtbLog.Document.Blocks.Clear() })

$BtnLaunch.Add_Click({
    $used = Start-GMApp
    if ($used) { Set-Status ('已启动 Galgame Manager（{0}）' -f $used) '#FFA6E3A1' }
    else {
        [System.Windows.MessageBox]::Show('找不到 Galgame Manager.exe，也没找到可用的 Python。', '提示', 'OK', 'Warning') | Out-Null
    }
})

$BtnOpenLog.Add_Click({
    if ($script:CurrentLog -and (Test-Path -LiteralPath $script:CurrentLog)) {
        Start-Process notepad.exe -ArgumentList ('"{0}"' -f $script:CurrentLog) | Out-Null
    } else {
        Start-Process explorer.exe -ArgumentList ('"{0}"' -f $LogDir) | Out-Null
    }
})

$BtnOpenFolder.Add_Click({
    $open = $ProjectRoot
    if (-not $RootOk) { $open = $ScriptRoot }
    Start-Process explorer.exe -ArgumentList ('"{0}"' -f $open) | Out-Null
})

$Window.Add_Closing({
    param($s, $e)
    if ($script:Running -and $script:Proc -and -not $script:Proc.HasExited) {
        $r = [System.Windows.MessageBox]::Show('任务正在运行，确定要退出吗？', '确认', 'YesNo', 'Question')
        if ($r -ne 'Yes') { $e.Cancel = $true; return }
        try { $script:Proc.Kill() } catch { }
    }
})

# ==============================================================================
# 启动
# ==============================================================================
Add-LogLine 'Galgame Manager 环境检测工具 v1.2 · 已就绪'
Add-LogLine ('工具目录: {0}' -f $ScriptRoot)
if ($RootOk) {
    if ($ProjectRoot -ne $ScriptRoot) {
        Add-LogLine ('项目目录: {0}   （已自动向上定位）' -f $ProjectRoot)
    } else {
        Add-LogLine ('项目目录: {0}' -f $ProjectRoot)
    }
} else {
    Add-LogLine '[WARN] 没有找到项目根目录（往上找不到含 src\main.py 与 data\ 的文件夹）！'
    Add-LogLine '       请把本工具放回 Galgame Manager 项目文件夹内再试。'
}
Add-LogLine ('日志目录: {0}' -f $LogDir)
Add-LogLine ''
Add-LogLine '点击「⚡ 一键安装」开始：会自动测速选出最快的镜像源，补齐缺失依赖并做启动前校验。'
Add-LogLine '只想看看不装东西 → 「🔍 仅检测」；只想测镜像速度 → 「📡 测速」。'
Add-LogLine ''
Update-AutoLaunchVisual
Set-Status '就绪' '#FFA6ADC8'

$null = $Window.ShowDialog()
