from src.gui.prompts import PromptsConfig
import json
import os
import shutil

def test_prompts_config():
    print("Testing PromptsConfig...")
    backup = False
    
    if os.path.exists("prompts.json"):
        shutil.copy("prompts.json", "prompts_backup.json")
        backup = True
        
    try:
        config = PromptsConfig()
        
        # Test 1: Clean start, are defaults properly tagged?
        text_edit_actions = config.get_text_edit_actions()
        print("Initial Explain action is_default:", text_edit_actions.get("Explain", {}).get("_is_default"))
        
        # Test 2: Modify something
        config._config["text_edit_tool"]["Explain"]["_is_default"] = False
        config._config["text_edit_tool"]["Explain"]["system_prompt"] += " Test suffix."
        config._save()
        
        # Reload
        config2 = PromptsConfig()
        config2.reload()
        text_edit_actions2 = config2.get_text_edit_actions()
        print("Reloaded Explain action is_default:", text_edit_actions2.get("Explain", {}).get("_is_default"))
        print("Reloaded Explain action system_prompt ends with:", text_edit_actions2.get("Explain", {}).get("system_prompt", "").endswith("Test suffix."))
        
        # Test 3: Tools Config
        from src.tools.config import load_tools_config
        
        # Cleanup
        if os.path.exists("tools_config.json"):
            os.remove("tools_config.json")
            
        tools_cfg = load_tools_config()
        print("Tools config OCR action is_default:", tools_cfg.get("file_processor", {}).get("prompts", {}).get("OCR (Verbatim)", {}).get("_is_default"))
        
        # Simulate user edit
        tools_cfg["file_processor"]["prompts"]["OCR (Verbatim)"]["_is_default"] = False
        tools_cfg["file_processor"]["prompts"]["OCR (Verbatim)"]["description"] += " Test desc"
        with open("tools_config.json", "w") as f:
            json.dump(tools_cfg, f)
            
        # load again
        tools_cfg_2 = load_tools_config()
        print("Reloaded Tools config OCR action is_default:", tools_cfg_2.get("file_processor", {}).get("prompts", {}).get("OCR (Verbatim)", {}).get("_is_default"))
        print("Reloaded Tools config OCR desc ends with:", tools_cfg_2.get("file_processor", {}).get("prompts", {}).get("OCR (Verbatim)", {}).get("description", "").endswith("Test desc"))

    finally:
        if backup:
            shutil.copy("prompts_backup.json", "prompts.json")
            os.remove("prompts_backup.json")
            
        if os.path.exists("tools_config.json"):
            os.remove("tools_config.json")

if __name__ == "__main__":
    test_prompts_config()