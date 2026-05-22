import argparse
import hashlib
import os
import sys
import time
import subprocess
from pathlib import Path
from mnemonic import Mnemonic

from .core import Vault, VaultManager
from .client import SyncthingClient

def generate_mnemonic():
    phrase = Mnemonic("english").generate(strength=128)
    print("🆕 Generated new BIP39 seed phrase:")
    print(f"   \033[1m{phrase}\033[0m")
    print("   💾 Write this down — it is the ONLY key to this folder globally.")
    return phrase

def get_dir_stats(path):
    if not os.path.exists(path):
        return 0, 0
    total_size = 0
    file_count = 0
    try:
        for entry in os.scandir(path):
            try:
                # Security Fix: follow_symlinks=False prevents infinite recursion 
                # caused by circular symlinks.
                if entry.is_file(follow_symlinks=False):
                    total_size += entry.stat(follow_symlinks=False).st_size
                    file_count += 1
                elif entry.is_dir(follow_symlinks=False):
                    s, c = get_dir_stats(entry.path)
                    total_size += s
                    file_count += c
            except OSError:
                # Handle permission errors gracefully
                pass
    except OSError:
        pass
    return total_size, file_count

def format_size(size):
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size < 1024.0:
            return f"{size:.1f}{unit}"
        size /= 1024.0
    return f"{size:.1f}PB"

def get_service_path():
    return Path.home() / ".config" / "systemd" / "user" / "seedst.service"

def is_systemd_available():
    try:
        subprocess.run(["systemctl", "--version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except FileNotFoundError:
        return False

def is_service_active():
    try:
        res = subprocess.run(
            ["systemctl", "--user", "is-active", "seedst.service"],
            stdout=subprocess.DEVNULL, 
            stderr=subprocess.DEVNULL
        )
        return res.returncode == 0
    except Exception:
        return False

def stop_service_if_active():
    """Stop the systemd service if it is currently running."""
    if is_systemd_available() and is_service_active():
        print("⏸️ Pausing background service for configuration update...")
        try:
            subprocess.run(["systemctl", "--user", "stop", "seedst.service"], check=True)
            return True
        except subprocess.CalledProcessError:
            print("⚠️ Failed to stop service.")
    return False

def start_service():
    """Start the systemd service."""
    if is_systemd_available():
        print("▶️ Resuming background service...")
        try:
            subprocess.run(["systemctl", "--user", "start", "seedst.service"], check=True)
        except subprocess.CalledProcessError:
            print("⚠️ Failed to start service.")

def check_linger():
    """Check if linger is enabled for the current user."""
    try:
        user = os.getlogin()
        linger_file = Path(f"/var/lib/systemd/linger/{user}")
        return linger_file.exists()
    except Exception:
        return False

def do_install():
    if not is_systemd_available():
        print("⚠️ Systemd not detected. Cannot install service.")
        return False

    service_path = get_service_path()
    service_path.parent.mkdir(parents=True, exist_ok=True)
    
    # 1. Find the script
    script_path = Path.cwd() / "seedst"
    if not script_path.exists():
        script_path = Path.home() / "seedst" / "seedst"

    if not script_path.exists():
        print("❌ Could not find the 'seedst' executable script.")
        return False

    # 2. Find the Python executable (prefer venv)
    venv_python = script_path.parent / ".venv" / "bin" / "python"
    
    if venv_python.exists():
        print(f"🐍 Using Virtual Environment: {venv_python}")
        exec_start = f"{venv_python} {script_path} start"
    else:
        print("🐍 Using System Python (No .venv found)")
        exec_start = f"{script_path} start"

    unit_file = f"""[Unit]
Description=SeedST Discovery Service
After=network.target syncthing.service

[Service]
Type=simple
ExecStart={exec_start}
Restart=on-failure
RestartSec=10

[Install]
WantedBy=default.target
"""
    
    service_path.write_text(unit_file)
    print(f"📝 Created service file at {service_path}")

    # 3. Enable Linger if not already enabled
    if not check_linger():
        print("🔄 Enabling user lingering (run at boot)...")
        try:
            subprocess.run(["loginctl", "enable-linger", os.getlogin()], check=True)
            print("✅ Linger enabled.")
        except (subprocess.CalledProcessError, FileNotFoundError):
            print("⚠️ Could not enable linger automatically (needs root).")
            print("   Please run this command manually to start service at boot:")
            print(f"   sudo loginctl enable-linger {os.getlogin()}")

    try:
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=True)
        subprocess.run(["systemctl", "--user", "enable", "seedst.service"], check=True)
        subprocess.run(["systemctl", "--user", "restart", "seedst.service"], check=True)
        print("✅ SeedST service installed and started!")
        return True
    except subprocess.CalledProcessError:
        print("❌ Failed to enable service.")
        return False

def do_uninstall():
    service_path = get_service_path()
    try:
        subprocess.run(["systemctl", "--user", "stop", "seedst.service"], stderr=subprocess.DEVNULL)
        subprocess.run(["systemctl", "--user", "disable", "seedst.service"], stderr=subprocess.DEVNULL)
        if service_path.exists():
            service_path.unlink()
            subprocess.run(["systemctl", "--user", "daemon-reload"])
        print("🗑️ SeedST service stopped and removed.")
    except FileNotFoundError:
        print("❌ Systemctl not found.")

def prompt_install():
    """Ask the user if they want to install the service."""
    if not is_systemd_available():
        return
    if is_service_active():
        return

    try:
        print()
        answer = input("❓ Install background service for auto-sync? [Y/n]: ").strip().lower()
        if answer in ['y', 'yes', '']:
            do_install()
        else:
            print("   Hint: Run './seedst install' later to enable background syncing.")
    except (EOFError, KeyboardInterrupt):
        print("\n   Hint: Run './seedst install' later to enable background syncing.")

def main():
    parser = argparse.ArgumentParser(description="seedst — connect to your folders from anywhere using only a BIP39 seed phrase")
    sub = parser.add_subparsers(dest="cmd", required=True)

    share = sub.add_parser("share", help="Share a folder")
    share.add_argument("folder", type=str)

    join = sub.add_parser("join", help="Join existing vault")
    join.add_argument("folder", type=str)
    join.add_argument("mnemonic", nargs="+")

    leave = sub.add_parser("leave", help="Stop sharing and remove a vault")
    leave.add_argument("folder", type=str)

    sub.add_parser("list", help="List your vaults")
    sub.add_parser("status", help="Show detailed status table")
    sub.add_parser("start", help="Run discovery service in foreground")
    
    install = sub.add_parser("install", help="Install and start the background service (Linux/Systemd)")
    sub.add_parser("uninstall", help="Stop and remove the background service")

    args = parser.parse_args()
    vm = VaultManager()

    if args.cmd == "install":
        do_install()
        return
    
    if args.cmd == "uninstall":
        do_uninstall()
        return

    if args.cmd == "list":
        vaults = vm.get_vaults()
        if not vaults:
            print("🌍 No vaults yet.")
        else:
            print(f"🌐 {len(vaults)} active vault{'s' if len(vaults)>1 else ''}:")
            for v in vaults:
                print(f"   • {v['label']}  |  {v['mnemonic'][:30]}...")
        return

    elif args.cmd == "status":
        try:
            st = SyncthingClient()
            st_folders_list = st.get_folders()
            st_folders_map = {f['id']: f for f in st_folders_list}
        except SystemExit:
            print("⚠️ Syncthing not running.")
            st_folders_list = []
            st_folders_map = {}

        vaults = vm.get_vaults()
        
        print(f"{'SEEDST LABEL':<20} | {'ST LABEL':<20} | {'SIZE':>10} | {'FILES':>7} | STATUS")
        print("-" * 85)

        processed_ids = set()

        if not vaults:
            print("📭 No SeedST vaults configured.")
        else:
            for v in vaults:
                label = v['label'][:18] + ".." if len(v['label']) > 20 else v['label']
                f_id = v['folder_id']
                processed_ids.add(f_id)
                
                st_data = st_folders_map.get(f_id)
                if st_data:
                    st_label = st_data.get('label', 'N/A')
                    st_label = st_label[:18] + ".." if len(st_label) > 20 else st_label
                    status = "✅ Syncing"
                    path = st_data.get('path', v['local_path'])
                else:
                    st_label = "N/A"
                    status = "⚠️ Missing in ST"
                    path = v['local_path']

                path = os.path.expanduser(path)

                if os.path.exists(path):
                    size, count = get_dir_stats(path)
                    size_str = format_size(size)
                    count_str = str(count)
                else:
                    size_str = "0B"
                    count_str = "0"
                    status = "❌ Path Missing"

                print(f"{label:<20} | {st_label:<20} | {size_str:>10} | {count_str:>7} | {status}")

        unmanaged_found = False
        for f in st_folders_list:
            if f['id'] not in processed_ids:
                if not unmanaged_found:
                    print("-" * 85)
                    unmanaged_found = True
                
                st_label = f.get('label', 'N/A')
                st_label = st_label[:18] + ".." if len(st_label) > 20 else st_label
                path = os.path.expanduser(f.get('path', ''))
                
                if os.path.exists(path):
                    size, count = get_dir_stats(path)
                    size_str = format_size(size)
                    count_str = str(count)
                    status = "⚠️ Unmanaged"
                else:
                    size_str = "0B"
                    count_str = "0"
                    status = "❌ Path Missing (Unmanaged)"

                print(f"{'(Unmanaged)':<20} | {st_label:<20} | {size_str:>10} | {count_str:>7} | {status}")

        print("-" * 85)
        return

    elif args.cmd == "share":
        folder_path = os.path.abspath(args.folder)
        if not os.path.isdir(folder_path):
            print(f"❌ Not a directory: {args.folder}")
            sys.exit(1)

        existing = vm.get_vault_by_path(folder_path)
        if existing:
            print(f"✅ This folder is already shared.")
            print(f"   Seed phrase: {existing['mnemonic']}")
            return

        # Atomic flow: Stop -> Modify -> Start
        was_active = stop_service_if_active()

        mnemonic = generate_mnemonic()
        seed = Mnemonic("english").to_seed(mnemonic)
        folder_id = hashlib.sha256(seed).hexdigest()[:32]

        syncthing = SyncthingClient()
        syncthing.add_folder(folder_path, Path(folder_path).name, folder_id)

        vm.add_vault(folder_path, mnemonic, folder_id)
        print(f"\n🎉 Vault created successfully!")
        
        if was_active:
            start_service()
        else:
            prompt_install()

    elif args.cmd == "join":
        mnemonic = " ".join(args.mnemonic).strip()
        folder_path = os.path.abspath(args.folder)

        if vm.get_vault_by_mnemonic(mnemonic):
            print("✅ This seed is already joined.")
            return

        if not Mnemonic("english").check(mnemonic):
            print("❌ Invalid seed phrase.")
            sys.exit(1)

        # Atomic flow: Stop -> Modify -> Start
        was_active = stop_service_if_active()

        if not os.path.isdir(folder_path):
            os.makedirs(folder_path, exist_ok=True)
            print(f"📁 Created local folder: {folder_path}")

        seed = Mnemonic("english").to_seed(mnemonic)
        folder_id = hashlib.sha256(seed).hexdigest()[:32]

        syncthing = SyncthingClient()
        syncthing.add_folder(folder_path, Path(folder_path).name, folder_id)

        vm.add_vault(folder_path, mnemonic, folder_id)
        print(f"\n✅ Successfully joined vault!")
        
        if was_active:
            start_service()
        else:
            prompt_install()

    elif args.cmd == "leave":
        folder_path = os.path.abspath(args.folder)
        vault = vm.get_vault_by_path(folder_path)
        
        if not vault:
            print(f"❌ No vault found at path: {folder_path}")
            sys.exit(1)

        # Atomic flow: Stop -> Modify -> Start
        was_active = stop_service_if_active()

        syncthing = SyncthingClient()
        syncthing.remove_folder(vault['folder_id'])
        vm.remove_vault(folder_path)
        print(f"👋 Successfully left vault: {vault['label']}")
        
        if was_active:
            start_service()

    elif args.cmd == "start":
        print("🚀 Starting seedst discovery service (Foreground)...\n")
        vaults = vm.get_vaults()

        if not vaults:
            print("📭 No vaults configured yet.")
            return

        print(f"🌐 Monitoring {len(vaults)} vault(s).")
        st = SyncthingClient()
        
        for v in vaults:
            vault = Vault(v["mnemonic"], v["folder_id"], v["local_path"], st)
            vault.start_networking()

        print("\n✅ Discovery active. Press Ctrl+C to stop.")

        try:
            while True:
                time.sleep(10)
        except KeyboardInterrupt:
            print("\n🛑 Shutting down...")

if __name__ == "__main__":
    main()
