/*
 * AIPromptBridge Launcher
 * 
 * A lightweight native launcher that starts the internal Python application.
 * Compiled with conditional symbols to create two variants:
 *   - GUI Mode (/define:GUI): No console window, fire-and-forget launch
 *   - Console Mode (/define:CONSOLE): With console, waits for exit
 * 
 * Build Commands:
 *   GUI:     csc /target:winexe /out:AIPromptBridge.exe /win32icon:icon.ico /define:GUI Launcher.cs
 *   Console: csc /target:exe /out:AIPromptBridge-Console.exe /win32icon:icon.ico /define:CONSOLE Launcher.cs
 */

using System;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;

class Launcher
{
    // For showing error message boxes in GUI mode
    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    private static extern int MessageBoxW(IntPtr hWnd, string text, string caption, uint type);
    
    // MessageBox constants
    private const uint MB_ICONERROR = 0x10;
    
    static int Main(string[] args)
    {
        // 1. Determine the directory where this launcher resides
        string baseDir = AppDomain.CurrentDomain.BaseDirectory;
        
        // 2. Construct path to internal executable
        string internalExe = Path.Combine(baseDir, "bin", "AIPromptBridge_Internal.exe");
        
        // 3. Validate internal executable exists
        if (!File.Exists(internalExe))
        {
            string errorMsg = $"Critical Error: Could not find application binary at:\n{internalExe}";
            
#if GUI
            MessageBoxW(IntPtr.Zero, errorMsg, "AIPromptBridge Error", MB_ICONERROR);
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
        string modeArgs = "--launched-mode=console --show-console";
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
            
            Process process = Process.Start(psi);
            // Don't wait - exit immediately and let the app run independently
            return 0;
#else
            // Console Mode: Inherit console, wait for exit
            psi.CreateNoWindow = false;
            
            Process process = Process.Start(psi);
            
            // Wait for the internal process to exit
            // This keeps the console window alive
            process.WaitForExit();
            return process.ExitCode;
#endif
        }
        catch (Exception ex)
        {
            string errorMsg = $"Failed to launch application:\n{ex.Message}";
            
#if GUI
            MessageBoxW(IntPtr.Zero, errorMsg, "AIPromptBridge Error", MB_ICONERROR);
#else
            Console.WriteLine("❌ " + errorMsg);
            Console.WriteLine("\nPress Enter to exit...");
            try { Console.ReadLine(); } catch { }
#endif
            return 1;
        }
    }
}
