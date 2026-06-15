import base64
import hashlib
import json
import os
import sys

SALT = b"AIPromptBridge::key-obfuscation::v1"


def make_key(hostname: str) -> bytes:
    return hashlib.sha256(hostname.encode("utf-8") + SALT).digest()


def decode(obf: str, key: bytes) -> str:
    data = base64.b64decode(obf[5:])  # strip "$OBF$"
    plain = bytes(b ^ key[i % len(key)] for i, b in enumerate(data))
    return plain.decode("utf-8")


def encode(plain: str, key: bytes) -> str:
    data = plain.encode("utf-8")
    obf = bytes(b ^ key[i % len(key)] for i, b in enumerate(data))
    return "$OBF$" + base64.b64encode(obf).decode()


def process(keys_json: dict, old_key: bytes, new_key: bytes) -> dict:
    changed = 0
    for pool in keys_json.get("pools", {}).values():
        for entry in pool.get("keys", []):
            val = entry.get("key", "")
            if val.startswith("$OBF$"):
                try:
                    plain = decode(val, old_key)
                    entry["key"] = encode(plain, new_key)
                    changed += 1
                except Exception as e:
                    print(f"  [!] Could not re-encode key '{entry.get('name')}': {e}")
    print(f"  Re-encoded {changed} key(s).")
    return keys_json


def main():
    print("=== AIPromptBridge Key Re-obfuscator ===\n")

    # Input file
    input_path = input("Path to keys.json [keys.json]: ").strip() or "keys.json"
    if not os.path.exists(input_path):
        print(f"[!] File not found: {input_path}")
        sys.exit(1)

    with open(input_path, encoding="utf-8") as f:
        keys_json = json.load(f)

    # Hostnames
    old_hostname = input("Old hostname (the machine that encoded these keys): ").strip()
    new_hostname = input("New hostname (this machine): ").strip()

    if not old_hostname or not new_hostname:
        print("[!] Hostname cannot be empty.")
        sys.exit(1)

    old_key = make_key(old_hostname)
    new_key = make_key(new_hostname)

    print(f"\nOld key (first 8 bytes): {list(old_key[:8])}")
    print(f"New key (first 8 bytes): {list(new_key[:8])}\n")

    # Quick sanity check: try to decode first key found
    for pool in keys_json.get("pools", {}).values():
        for entry in pool.get("keys", []):
            val = entry.get("key", "")
            if val.startswith("$OBF$"):
                try:
                    sample = decode(val, old_key)
                    print(f"Sanity check — decoded '{entry.get('name')}': {sample[:6]}***")
                    confirm = input("Does this look right? (y/n): ").strip().lower()
                    if confirm != "y":
                        print("[!] Aborted. Please double-check the old hostname.")
                        sys.exit(1)
                except Exception as e:
                    print(f"[!] Sanity check failed ({e}). Wrong old hostname?")
                    sys.exit(1)
                break
        else:
            continue
        break

    # Process
    print("\nRe-encoding all keys...")
    updated = process(keys_json, old_key, new_key)

    # Output file
    output_path = input("\nSave to [keys.json]: ").strip() or "keys.json"
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(updated, f, indent=2, ensure_ascii=False)
    print(f"\n[✓] Saved to: {output_path}")


if __name__ == "__main__":
    main()
