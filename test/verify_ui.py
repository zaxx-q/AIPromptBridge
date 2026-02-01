import tkinter as tk
import sys
import os
sys.path.append(os.getcwd())

from src.gui.prompt_editor import PromptEditorWindow, HAVE_CTK
if HAVE_CTK:
    import customtkinter as ctk

def verify():
    print("Starting verification...")
    if HAVE_CTK:
        root = ctk.CTk()
    else:
        root = tk.Tk()
        
    app = PromptEditorWindow(master=root)
    app.show()
    
    # Simple check if widgets exist
    print("Checking widgets...")
    try:
        if hasattr(app, "tool_switcher"):
            print("PASS: Tool switcher exists")
        else:
            print("FAIL: Tool switcher missing")
            
        # Check current tool
        if app.current_tool == "text_edit_tool":
            print("PASS: Default tool is text_edit_tool")
        else:
            print(f"FAIL: Default tool is {app.current_tool}")
            
        # Check Playground Mode (new default is action_text)
        if hasattr(app, "playground_mode_var"):
            mode = app.playground_mode_var.get() 
            if mode == "action_text":
                print("PASS: Default playground mode is action_text")
            else:
                print(f"FAIL: Default playground mode is {mode}")
        else:
            print("FAIL: playground_mode_var missing")

        if hasattr(app, "image_upload_container"):
            # Should be MISSING now or None if I removed it correctly (Wait, I removed the lines populating it, so the attribute might not exist)
            pass 
            
        # Check Snip Logic
        if hasattr(app, "_perform_snip_test"):
             print("PASS: Snip simulation logic exists")
        else:
             print("FAIL: Snip simulation logic missing")
             
        # Check Endpoint Logic
        if hasattr(app, "_populate_endpoint_list"):
             print("PASS: Endpoint population logic exists")
        else:
             print("FAIL: Endpoint population logic missing")
            
        print("UI initialized successfully. Closing in 3 seconds...")
        root.after(3000, root.destroy)
        root.mainloop()
        print("Verification complete.")
    except Exception as e:
        print(f"FAIL: Verification crashed: {e}")

if __name__ == "__main__":
    verify()
