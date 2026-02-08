/*
 * AIPromptBridge Launcher
 *
 * A lightweight native launcher that starts the internal Python application.
 * Compiled with conditional symbols to create two variants:
 *   - No Console Mode (/define:GUI): No console window, fire-and-forget launch
 *   - Console Mode (/define:CONSOLE): With console, waits for exit
 *
 * Build Commands (Managed by GitHub Actions):
 *   Console:    csc /target:exe /out:AIPromptBridge.exe /win32icon:icon.ico /define:CONSOLE /reference:System.Windows.Forms.dll Launcher.cs Properties/AssemblyInfo.cs
 *   No Console: csc /target:winexe /out:AIPromptBridge-NoConsole.exe /win32icon:icon.ico /define:GUI /reference:System.Windows.Forms.dll Launcher.cs Properties/AssemblyInfo.cs
 */

using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms; // Requires /reference:System.Windows.Forms.dll

class Launcher
{
    [STAThread] // Good practice for UI apps, even if just showing MessageBox
    static int Main(string[] args)
    {
        // 1. Determine the directory where this launcher resides
        string baseDir = AppDomain.CurrentDomain.BaseDirectory;
        
        // 2. Construct path to internal executable
        string internalExe = Path.Combine(baseDir, "bin", "AIPromptBridge_Internal.exe");
        
        // 3. Validate internal executable exists
        if (!File.Exists(internalExe))
        {
            string errorMsg = "Critical Error: Could not find application binary at:\n" + internalExe;
            
#if GUI
            MessageBox.Show(errorMsg, "AIPromptBridge Error", MessageBoxButtons.OK, MessageBoxIcon.Error);
#else
            Console.WriteLine("❌ " + errorMsg);
            Console.WriteLine("\nPress Enter to exit...");
            try { Console.ReadLine(); } catch { }
#endif
            return 1;
        }
        
        // 4. Build arguments
        //    Prepend our mode flag, then pass through all original arguments
#if GUI
        string modeArgs = "--launched-mode=gui";
#else
        string modeArgs = "--launched-mode=console";
#endif
        
        string allArgs = modeArgs;
        if (args.Length > 0)
        {
            allArgs += " " + string.Join(" ", args);
        }
        
        // 5. Launch the internal executable
        try
        {
            ProcessStartInfo psi = new ProcessStartInfo
            {
                FileName = internalExe,
                Arguments = allArgs,
                UseShellExecute = false,
                WorkingDirectory = baseDir
            };
            
#if GUI
            // GUI Mode: Fire and forget, no console window
            psi.CreateNoWindow = true;
            psi.WindowStyle = ProcessWindowStyle.Hidden;
            
            Process.Start(psi);
            // Don't wait - exit immediately and let the app run independently
            return 0;
#else
            // Console Mode: Inherit console, wait for exit
            psi.CreateNoWindow = false;
            
            Process process = Process.Start(psi);
            
            // Wait for the internal process to exit
            // This keeps the console window alive
            if (process != null)
            {
                process.WaitForExit();
                return process.ExitCode;
            }
            return 0;
#endif
        }
        catch (Exception ex)
        {
            string errorMsg = "Failed to launch application:\n" + ex.Message;
            
#if GUI
            MessageBox.Show(errorMsg, "AIPromptBridge Error", MessageBoxButtons.OK, MessageBoxIcon.Error);
#else
            Console.WriteLine("❌ " + errorMsg);
            Console.WriteLine("\nPress Enter to exit...");
            try { Console.ReadLine(); } catch { }
#endif
            return 1;
        }
    }
}
