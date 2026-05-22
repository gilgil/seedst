import hashlib
import json
import os
import time
import threading
from pathlib import Path

from mnemonic import Mnemonic
from Crypto.Cipher import AES
from Crypto.Util.Padding import pad, unpad
import paho.mqtt.client as mqtt_client

from .client import SyncthingClient

CONFIG_DIR = Path.home() / ".seedst"
VAULTS_FILE = CONFIG_DIR / "vaults.json"

# Maximum age of a discovery message in seconds (2 minutes)
# Messages with timestamps older than this will be rejected to prevent replay attacks.
MAX_MESSAGE_AGE = 120

class Vault:
    def __init__(self, mnemonic: str, folder_id: str, local_path: str, st_client: SyncthingClient):
        self.mnemonic = mnemonic
        self.folder_id = folder_id
        self.local_path = local_path
        self.st = st_client
        self.seed = Mnemonic("english").to_seed(mnemonic)
        self.room_id = hashlib.sha256(self.seed).hexdigest()
        self.topic = f"seedst/{self.room_id}/announce"

        # Derive a 32-byte AES key from the seed using SHA256
        # Since everyone has the same seed, everyone derives the same key.
        self.aes_key = hashlib.sha256(self.seed).digest()

        self.my_device_id = st_client.get_device_id()
        self.running = True
        self.client = None
        self.known_peers = set()

    def start_networking(self):
        self.client = mqtt_client.Client()
        self.client.on_message = self.on_message
        self.client.on_connect = self.on_connect
        
        try:
            self.client.connect("broker.hivemq.com", 1883, 60)
            self.client.loop_start()
        except Exception as e:
            print(f"❌ MQTT Connection error: {e}")
            return

        threading.Thread(target=self._announce_loop, daemon=True).start()

    def on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            client.subscribe(self.topic, qos=1)
            self.publish_announcement()

    def _announce_loop(self):
        while self.running:
            time.sleep(15)
            self.publish_announcement()

    def publish_announcement(self):
        if not self.client or not self.client.is_connected(): return
            
        payload = {
            "device_id": self.my_device_id,
            "folder_id": self.folder_id,
            "name": os.uname().nodename,
            "timestamp": time.time()
        }
        try:
            # Use AES Encryption
            data = json.dumps(payload).encode()
            cipher = AES.new(self.aes_key, AES.MODE_GCM)
            ciphertext, tag = cipher.encrypt_and_digest(data)
            # Combine nonce, tag, and ciphertext for transport
            encrypted_payload = cipher.nonce + tag + ciphertext
            
            self.client.publish(self.topic, encrypted_payload, qos=1)
        except Exception as e:
            print(f"Encryption error: {e}")

    def on_message(self, client, userdata, msg):
        try:
            encrypted_payload = msg.payload
            
            # Extract nonce (16 bytes), tag (16 bytes), and ciphertext
            nonce = encrypted_payload[:16]
            tag = encrypted_payload[16:32]
            ciphertext = encrypted_payload[32:]
            
            # Decrypt
            cipher = AES.new(self.aes_key, AES.MODE_GCM, nonce=nonce)
            data = json.loads(cipher.decrypt_and_verify(ciphertext, tag).decode())
            
            # Security: Prevent Replay Attacks
            # Check if the message timestamp is recent
            msg_time = data.get("timestamp", 0)
            if time.time() - msg_time > MAX_MESSAGE_AGE:
                # print(f"⚠️ Ignoring stale replay message from {data.get('name')}") # Optional debug
                return

            if data["device_id"] == self.my_device_id: return
            if data["device_id"] in self.known_peers: return

            print(f"🔍 Peer discovered → {data['name']}")
            self.known_peers.add(data["device_id"])
            
            self.st.add_device(data["device_id"], data["name"])
            self.st.share_folder_with_device(self.folder_id, data["device_id"])
            
        except Exception as e:
            # Decryption failed (wrong key) or invalid payload
            # print(f"Debug: Message processing error: {e}") 
            pass


class VaultManager:
    def __init__(self):
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        if not VAULTS_FILE.exists():
            VAULTS_FILE.write_text(json.dumps({"vaults": []}, indent=2))
        self.data = json.loads(VAULTS_FILE.read_text())

    def save(self):
        VAULTS_FILE.write_text(json.dumps(self.data, indent=2))

    def get_vault_by_path(self, path: str):
        p = os.path.abspath(path)
        for v in self.data["vaults"]:
            if os.path.abspath(v["local_path"]) == p:
                return v
        return None

    def get_vault_by_mnemonic(self, mnemonic: str):
        for v in self.data["vaults"]:
            if v["mnemonic"] == mnemonic:
                return v
        return None

    def get_vaults(self):
        return self.data["vaults"]

    def add_vault(self, local_path: str, mnemonic: str, folder_id: str):
        self.data["vaults"].append({
            "local_path": str(local_path),
            "mnemonic": mnemonic,
            "folder_id": folder_id,
            "label": Path(local_path).name
        })
        self.save()

    def remove_vault(self, path: str):
        abs_path = os.path.abspath(path)
        original_count = len(self.data["vaults"])
        self.data["vaults"] = [v for v in self.data["vaults"] if os.path.abspath(v["local_path"]) != abs_path]
        if len(self.data["vaults"]) < original_count:
            self.save()
            return True
        return False
