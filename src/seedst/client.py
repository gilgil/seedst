import os
import requests
import xml.etree.ElementTree as ET
from pathlib import Path

class SyncthingClient:
    def __init__(self):
        self.api_key, self.base_url = self._load_config()
        self.session = requests.Session()
        self.session.headers.update({"X-API-Key": self.api_key})
        self.session.verify = False

    def _load_config(self):
        candidates = [
            Path.home() / ".config/syncthing/config.xml",
            Path.home() / ".local/state/syncthing/config.xml",
            Path(os.getenv("XDG_STATE_HOME", Path.home() / ".local/state")) / "syncthing/config.xml",
        ]
        for path in candidates:
            if path.exists():
                try:
                    tree = ET.parse(path)
                    gui = tree.find(".//gui")
                    if gui is not None:
                        key = gui.find("apikey")
                        addr = gui.find("address")
                        tls = gui.find("tls")
                        if key is not None and key.text and key.text.strip():
                            scheme = "https" if (tls is not None and tls.text == "true") else "http"
                            addr_text = addr.text if addr is not None else "127.0.0.1:8384"
                            if addr_text.startswith("0.0.0.0"):
                                addr_text = addr_text.replace("0.0.0.0", "127.0.0.1")
                            url = f"{scheme}://{addr_text}"
                            return key.text.strip(), url
                except Exception:
                    continue
        raise SystemExit("❌ Could not find Syncthing config.xml.")

    def get_device_id(self):
        try:
            r = self.session.get(f"{self.base_url}/rest/system/status", timeout=5)
            r.raise_for_status()
            return r.json()["myID"]
        except requests.exceptions.ConnectionError:
            raise SystemExit(
                "❌ Cannot connect to Syncthing.\n\n"
                "   Please start Syncthing first:\n"
                "      syncthing\n\n"
                "   Then run `./seedst start` again."
            )

    def get_folders(self):
        r = self.session.get(f"{self.base_url}/rest/config/folders")
        r.raise_for_status()
        return r.json()

    def get_folder_by_path(self, path: str):
        abs_path = os.path.abspath(path)
        for f in self.get_folders():
            if os.path.abspath(f.get("path", "")) == abs_path:
                return f
        return None

    def add_folder(self, local_path: str, label: str, folder_id: str):
        for f in self.get_folders():
            if f["id"] == folder_id:
                return # Already exists

        folder = {
            "id": folder_id,
            "label": label,
            "path": str(local_path),
            "type": "sendreceive",
            "rescanIntervalS": 3600,
            "fsWatcherEnabled": True,
            "autoNormalize": True,
        }
        r = self.session.post(f"{self.base_url}/rest/config/folders", json=folder)
        r.raise_for_status()

    def remove_folder(self, folder_id: str):
        # Syncthing API returns 204 No Content on success
        r = self.session.delete(f"{self.base_url}/rest/config/folders/{folder_id}")
        if r.status_code not in [200, 204]:
            print(f"⚠️ Warning: Could not remove folder from Syncthing: {r.text}")
        else:
            print(f"🗑️ Removed folder {folder_id[:8]}... from Syncthing config.")

    def add_device(self, device_id: str, name: str):
        r = self.session.get(f"{self.base_url}/rest/config/devices/{device_id}")
        if r.status_code == 200:
            return # Already exists

        device_config = {
            "deviceID": device_id,
            "name": name,
            "autoAcceptFolders": True,
            "addresses": ["dynamic"],
        }
        r = self.session.post(f"{self.base_url}/rest/config/devices", json=device_config)
        r.raise_for_status()

    def share_folder_with_device(self, folder_id: str, device_id: str):
        r = self.session.get(f"{self.base_url}/rest/config/folders/{folder_id}")
        if r.status_code != 200: return
        
        folder = r.json()
        if any(d["deviceID"] == device_id for d in folder.get("devices", [])):
            return

        folder["devices"].append({"deviceID": device_id})
        r = self.session.put(f"{self.base_url}/rest/config/folders/{folder_id}", json=folder)
        r.raise_for_status()
