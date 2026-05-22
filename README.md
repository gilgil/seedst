# SeedST (Seed Syncthing)

A command-line tool to bootstrap Syncthing connections using a BIP39 seed phrase.

SeedST removes the friction of sharing Syncthing Folder IDs and Device IDs. Instead of manually copying/pasting long hexadecimal strings, you simply share a 12-word mnemonic phrase. Any device with the same phrase will automatically discover each other and configure Syncthing to sync.

## Features

- **One Command Setup**: Share a folder with a single command.
- **Mnemonic Based**: Uses standard BIP39 12-word seeds for easy transcription and backup.
- **Encrypted Discovery**: Uses **AES-256-GCM** (Symmetric Encryption) to secure discovery messages over MQTT.
- **Background Service**: Installs a user-level Systemd service for auto-start and crash recovery.
- **Cross-Platform**: Works on Linux, macOS, and Android (Termux). (Service management is Linux-specific).
- **Status Dashboard**: Monitor your vaults, sizes, and file counts at a glance.

## Prerequisites

1. **Python 3.6+**
2. **Syncthing**: Must be installed and running on the local machine.
   - *Note: SeedST uses the local Syncthing REST API to configure folders and devices.*

## Installation

1. Clone the repository:
   ```bash
   git clone https://github.com/yourusername/seedst.git
   cd seedst
   ```

2. Create a virtual environment and install dependencies:
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```

3. Make the script executable:
   ```bash
   chmod +x seedst
   ```

## Usage

### Step 1: Share a Folder (Machine A)

Run the share command on the machine containing the data you want to sync.

```bash
./seedst share /path/to/your/folder
```

**Output:**
```
🆕 Generated new BIP39 seed phrase:
   river feel catalog agent ... kitchen
   💾 Write this down — it is the ONLY key to this folder globally.
✅ Added folder to Syncthing: folder (ID: a1b2c3d4...)
🎉 Vault created successfully!

❓ Install background service for auto-sync? [Y/n]: 
```

**Copy the 12-word seed phrase.**

### Step 2: Join the Vault (Machine B)

On the second machine, use the `join` command with the seed phrase to sync the data to a local path.

*Note: The folder path comes first, followed by the seed words.*

```bash
./seedst join /local/path/to/sync river feel catalog agent ... kitchen
```

### Step 3: Enable Background Syncing

After `share` or `join`, you will be prompted to install the background service. If you chose 'n' or want to do it manually later:

```bash
./seedst install
```

This creates a user-level Systemd service that:
- Starts automatically when you log in.
- Restarts automatically if it crashes.
- Runs quietly in the background.

**For Servers (Headless):**
To keep the service running even after you log out (essential for servers), you must enable "lingering". The install command attempts this, but if it fails (needs root), run:
```bash
sudo loginctl enable-linger $USER
```

### Monitoring & Management

#### Status
View a detailed table of all SeedST vaults and unmanaged Syncthing folders, including file counts and sizes.

```bash
./seedst status
```

**Output:**
```
SEEDST LABEL         | ST LABEL             |       SIZE |   FILES | STATUS
-------------------------------------------------------------------------------------
vault                | vault                |     43.3KB |      50 | ✅ Syncing
-------------------------------------------------------------------------------------
(Unmanaged)          | Default Folder       |       0.0B |       0 | ⚠️ Unmanaged
-------------------------------------------------------------------------------------
```

#### List
See a simple list of configured vaults.

```bash
./seedst list
```

#### Leave
Stop sharing a folder. This removes it from the SeedST database and the Syncthing configuration.

```bash
./seedst leave /path/to/folder
```

#### Uninstall Service
Stop and remove the background service.

```bash
./seedst uninstall
```

## How It Works

1.  **Deterministic IDs**: The script hashes the BIP39 seed to generate a deterministic Syncthing Folder ID. This ensures both machines configure the exact same Folder ID without communication.
2.  **Discovery (MQTT)**: The script connects to a public MQTT broker (`broker.hivemq.com`) on a topic derived from the seed hash.
3.  **Security (AES-256-GCM)**:
    - The seed is used to derive a shared AES-256 key.
    - When announcing, the script generates a random **Nonce**, encrypts the payload (Device ID, etc.), and broadcasts the Nonce + Ciphertext.
    - Only devices with the same seed (and thus the same AES key) can decrypt the message.
    - The random Nonce ensures that every encrypted message looks different, preventing replay attacks.
4.  **Automation**: Upon decrypting a peer's message, the script uses the Syncthing REST API to add the remote device and share the folder with it.

## Security Notice

- **Seed Phrase Safety**: Treat the seed phrase like a password. Anyone with the phrase can decrypt your discovery messages and request to sync with your folder.
- **Local Trust**: The script modifies the local Syncthing configuration (`config.xml`) via the API.
- **Transport**: Discovery traffic is encrypted via AES-256, but the actual file sync relies on Syncthing's existing TLS implementation.

## License

MIT License