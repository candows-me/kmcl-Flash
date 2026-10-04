using System;
using System.Diagnostics;
using System.IO;

// KMCL 社区维护版 - 启动器壳
// 双击本 exe：无任何黑色控制台窗口，直接调用内置 Python (pythonw.exe) 运行 main.py
namespace KMCL
{
    class Launcher
    {
        [STAThread]
        static void Main()
        {
            try
            {
                string dir = AppDomain.CurrentDomain.BaseDirectory;
                string py = Path.Combine(dir, "python", "pythonw.exe");
                if (!File.Exists(py))
                    py = Path.Combine(dir, "python", "python.exe");
                if (!File.Exists(py))
                {
                    File.WriteAllText(Path.Combine(dir, "launcher_error.txt"),
                        "[KMCL] 未找到内置 Python 运行时。\n请确认 python\\ 文件夹存在。");
                    return;
                }
                Process p = new Process();
                p.StartInfo.FileName = py;
                p.StartInfo.Arguments = "\"main.py\"";
                p.StartInfo.WorkingDirectory = dir;
                p.StartInfo.UseShellExecute = false;
                p.Start();
            }
            catch (Exception ex)
            {
                try
                {
                    File.WriteAllText(
                        Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "launcher_error.txt"),
                        ex.ToString());
                }
                catch { }
            }
        }
    }
}
