using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

// Galgame Memoir 启动器
//   - 双击本 exe 即可启动（不带黑框）
//   - 自动找 pythonw.exe / python.exe / pyw.exe / py.exe
//   - 依赖缺失时自动转到 repair\repair.bat 走可见的安装流程
internal static class Launcher
{
    private const string AppTitle = "Galgame Manager";

    [STAThread]
    private static void Main()
    {
        string dir;
        try { dir = Path.GetFullPath(AppDomain.CurrentDomain.BaseDirectory); }
        catch { dir = Environment.CurrentDirectory; }

        string mainPy = Path.Combine(Path.Combine(dir, "src"), "main.py");
        string bat = Path.Combine(Path.Combine(dir, "repair"), "repair.bat");

        if (!File.Exists(mainPy))
        {
            Fail("\u627e\u4e0d\u5230\u4e3b\u7a0b\u5e8f\uff1a\n" + mainPy +
                 "\n\n\u8bf7\u4fdd\u6301\u672c exe \u4e0e src \u76ee\u5f55\u5728\u540c\u4e00\u5c42\u3002");
            return;
        }

        string pyw = FindOnPath("pythonw.exe");
        string py = FindOnPath("python.exe");
        string pyw2 = FindOnPath("pyw.exe");
        string py2 = FindOnPath("py.exe");
        if (pyw == null && py == null && pyw2 == null && py2 == null)
        {
            Fail("\u6ca1\u6709\u68c0\u6d4b\u5230 Python\u3002\n\n\u8bf7\u5148\u5b89\u88c5 Python 3.9 \u6216\u66f4\u65b0\u7248\u672c\uff1a\n" +
                 "https://www.python.org/downloads/\n\n\u5b89\u88c5\u65f6\u8bf7\u52a1\u5fc5\u52fe\u9009 \u201cAdd Python to PATH\u201d\u3002");
            return;
        }

        // \u5148\u7528\u80fd\u62ff\u5230\u9000\u51fa\u7801\u7684\u89e3\u91ca\u5668\u68c0\u67e5\u4f9d\u8d56
        string checker = py != null ? py : (py2 != null ? py2 : (pyw2 != null ? pyw2 : pyw));
        int rc = RunHidden(checker, "-c \"import PySide6, requests, PIL\"", dir, 120000);
        if (rc != 0)
        {
            if (File.Exists(bat))
            {
                try
                {
                    ProcessStartInfo bi = new ProcessStartInfo();
                    bi.FileName = bat;
                    bi.WorkingDirectory = dir;
                    bi.UseShellExecute = true;
                    Process.Start(bi);
                    return;
                }
                catch { }
            }
            Fail("\u8fd0\u884c\u4f9d\u8d56\u4e0d\u5b8c\u6574\uff08PySide6 / requests / pillow\uff09\u3002\n\n" +
                 "\u8bf7\u8054\u7f51\u540e\u53cc\u51fb repair \u6587\u4ef6\u5939\u91cc\u7684 repair.bat \u8ba9\u5b83\u81ea\u52a8\u8865\u88c5\u4f9d\u8d56\u3002");
            return;
        }

        string runner = pyw != null ? pyw : (pyw2 != null ? pyw2 : (py != null ? py : py2));
        try
        {
            ProcessStartInfo psi = new ProcessStartInfo();
            psi.FileName = runner;
            psi.Arguments = "\"" + mainPy + "\"";
            psi.WorkingDirectory = dir;
            psi.UseShellExecute = false;
            psi.CreateNoWindow = true;
            Process.Start(psi);
        }
        catch (Exception ex)
        {
            Fail("\u542f\u52a8\u5931\u8d25\uff1a\n" + ex.Message);
        }
    }

    // \u5728 PATH \u91cc\u627e\u53ef\u6267\u884c\u6587\u4ef6\uff08\u6392\u9664 Microsoft Store \u7684 0 \u5b57\u8282\u5047\u58f3\uff09
    private static string FindOnPath(string exe)
    {
        try
        {
            string path = Environment.GetEnvironmentVariable("PATH");
            if (path == null || path.Length == 0) return null;
            string[] parts = path.Split(';');
            for (int i = 0; i < parts.Length; i++)
            {
                string p = parts[i].Trim().Trim('"');
                if (p.Length == 0) continue;
                string full;
                try { full = Path.Combine(p, exe); } catch { continue; }
                if (!File.Exists(full)) continue;
                try
                {
                    FileInfo fi = new FileInfo(full);
                    if (fi.Length == 0) continue;
                }
                catch { }
                return full;
            }
        }
        catch { }
        return null;
    }

    private static int RunHidden(string exe, string args, string workdir, int timeoutMs)
    {
        try
        {
            ProcessStartInfo psi = new ProcessStartInfo();
            psi.FileName = exe;
            psi.Arguments = args;
            psi.WorkingDirectory = workdir;
            psi.UseShellExecute = false;
            psi.CreateNoWindow = true;
            psi.RedirectStandardOutput = true;
            psi.RedirectStandardError = true;
            using (Process p = Process.Start(psi))
            {
                p.StandardOutput.ReadToEnd();
                p.StandardError.ReadToEnd();
                if (!p.WaitForExit(timeoutMs))
                {
                    try { p.Kill(); } catch { }
                    return -1;
                }
                return p.ExitCode;
            }
        }
        catch { return -1; }
    }

    private static void Fail(string msg)
    {
        try { MessageBox.Show(msg, AppTitle, MessageBoxButtons.OK, MessageBoxIcon.Warning); }
        catch { }
    }
}
