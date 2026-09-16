using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

// ============================================================================
//  Galgame Manager 环境检测工具 —— 无黑框启动器
//
//  双击本 exe 就直接打开图形界面，全程不会出现控制台/Windows Terminal 窗口。
//
//  为什么要这个 exe：
//    .bat 里写的 `powershell -WindowStyle Hidden` 在 Windows 11 上并不可靠 ——
//    只要系统把「Windows Terminal」设成了默认终端应用，隐藏请求就会被忽略，
//    黑框照样弹出来；一旦关掉它，powershell 被结束，整个图形界面也跟着退出。
//    本启动器改用 CreateNoWindow（等价于 CreateProcess 的 CREATE_NO_WINDOW），
//    控制台窗口从一开始就不会被创建，所以任何终端宿主都无从显示。
//
//  保持本 exe 与 环境检测工具.ps1 放在同一个文件夹里。
// ============================================================================
internal static class Launcher
{
    private const string AppTitle  = "Galgame Manager \u73af\u5883\u68c0\u6d4b\u5de5\u5177";
    private const string ScriptName = "\u73af\u5883\u68c0\u6d4b\u5de5\u5177.ps1";

    [STAThread]
    private static void Main()
    {
        string dir;
        try { dir = Path.GetFullPath(AppDomain.CurrentDomain.BaseDirectory); }
        catch { dir = Environment.CurrentDirectory; }

        string script = Path.Combine(dir, ScriptName);
        if (!File.Exists(script))
        {
            MessageBox.Show(
                "\u627e\u4e0d\u5230\u540c\u76ee\u5f55\u4e0b\u7684 " + ScriptName + "\u3002\n\n" +
                "\u8bf7\u628a\u672c exe \u4e0e\u5b83\u653e\u5728\u540c\u4e00\u4e2a\u6587\u4ef6\u5939\u91cc\u3002",
                AppTitle, MessageBoxButtons.OK, MessageBoxIcon.Error);
            return;
        }

        ProcessStartInfo psi = new ProcessStartInfo();
        psi.FileName        = "powershell.exe";
        // -WindowStyle Hidden 保留一份保险；真正起作用的是 CreateNoWindow
        psi.Arguments       = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File \"" + script + "\"";
        psi.WorkingDirectory = dir;
        psi.UseShellExecute = false;
        psi.CreateNoWindow  = true;

        try
        {
            Process.Start(psi);
        }
        catch (Exception ex)
        {
            MessageBox.Show(
                "\u542f\u52a8\u5931\u8d25\uff1a\n" + ex.Message,
                AppTitle, MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }
}
