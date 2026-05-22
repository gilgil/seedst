# SeedST Architecture

This document outlines the technical architecture, data flows, and security model of the `seedst` application.

## High-Level Overview

SeedST acts as a bridge between a human-memorable secret (a BIP39 mnemonic) and the complex machine-readable configurations required by Syncthing (Device IDs, Folder IDs).

It automates the "introduction" phase of setting up a synced folder and manages the background discovery process via a Systemd user service.

```text
+-------------------+       MQTT (Public Broker)       +-------------------+
|      Device A     | <----------------------------- > |      Device B     |
| (seedst.service)  |                                 | (seedst.service)  |
+---------+---------+                                 +---------+---------+
          |                                                     |
          | (1. Derive ID & Key)                                | (1. Derive ID & Key)
          |                                                     |
          v                                                     v
+---------+---------+                                 +---------+---------+
|   Local Vault     |                                 |   Local Vault     |
| Mnemonic: "..."   |                                 | Mnemonic: "..."   |
| Folder ID: 0x1a.. |                                 | Folder ID: 0x1a.. |
+---------+---------+                                 +---------+---------+
          |                                                     |
          | (2. REST API)                                       | (2. REST API)
          v                                                     v
+---------+---------+                                 +---------+---------+
|   Syncthing A     | <===== (3. Syncthing Protocol) =>|   Syncthing B     |
| Folder: /data     |         (Direct P2P Sync)        | Folder: /data     |
+-------------------+                                 +-------------------+
```

## Core Components

### 1. CLI Interface (`cli.py`)
- **Library**: `argparse`
- **Responsibility**: Parses user commands (`share`, `join`, `leave`, `status`, `install`, `start`) and orchestrates the `VaultManager` and `SyncthingClient`.
- **Service Integration**: It detects if the Systemd service is running and performs atomic configuration updates (Stop Service -> Modify Config -> Start Service) to prevent race conditions.

### 2. VaultManager
- **Storage**: `~/.seedst/vaults.json`
- **Responsibility**: Persists the mapping between local paths, mnemonics, and generated Folder IDs. It ensures the script remembers which folders are under SeedST management.

### 3. SyncthingClient
- **Transport**: HTTP/HTTPS (REST API)
- **Discovery**: Parses `config.xml` to find the API key and GUI address.
- **Responsibility**: Abstracts the Syncthing REST API. It handles:
    - Adding folders (`POST /rest/config/folders`)
    - Removing folders (`DELETE /rest/config/folders/{id}`)
    - Adding devices (`POST /rest/config/devices`)
    - Sharing folders with devices (`PUT /rest/config/folders/{id}`)

### 4. Vault & Cryptography
- **Libraries**: `mnemonic`, `hashlib`, `pycryptodome`
- **Responsibility**: Handles the deterministic generation of IDs and the symmetric encryption of discovery payloads.

## Data Flow & Logic

### Phase 1: Initialization (`share` / `join`)

1. **Input**: User provides a mnemonic (or one is generated).
2. **Atomic Update**:
   - If the background service is running, it is stopped to ensure configuration consistency.
3. **Derivation**:
   - `Seed` = Mnemonic.to_seed(mnemonic)
   - `Folder ID` = SHA256(Seed)[:32]
   - `AES Key` = SHA256(Seed) (Derived once, used for all encryption/decryption)
4. **Configuration**:
   - The script calls the Syncthing API to create a folder with the derived `Folder ID`.
   - The mapping is saved to `vaults.json`.
   - The background service is restarted if it was previously active.

*Note: Both devices independently derive the identical `Folder ID` and `AES Key` from the shared secret.*

### Phase 2: Discovery (`start` / Service)

1. **MQTT Connection**:
   - The process connects to `broker.hivemq.com`.
   - It subscribes to the topic: `seedst/{SHA256(Seed)}/announce`.

2. **Announcement Loop**:
   - Every 15 seconds, the script publishes a payload.
   - **Encryption (AES-256-GCM)**:
     - A random 16-byte **Nonce** is generated for every message.
     - The payload is encrypted using the shared AES Key and the Nonce.
     - The published message = `Nonce` + `Tag` + `Ciphertext`.
   - **Payload Content**:
     ```json
     {
       "device_id": "SYNCTHING-DEVICE-ID",
       "folder_id": "DERIVED-FOLDER-ID",
       "name": "Hostname",
       "timestamp": 1678900000
     }
     ```

3. **Reception & Handshake**:
   - When a message is received:
     1. Extract Nonce and Tag.
     2. Attempt to decrypt using the shared AES Key.
     3. If decryption fails or sender is self, ignore.
     4. If successful, extract the remote `device_id`.
     5. Call Syncthing API: `add_device(remote_device_id)`.
     6. Call Syncthing API: `share_folder_with_device(folder_id, remote_device_id)`.

## Service Architecture

SeedST installs a user-level Systemd service to handle background discovery.

### Service File (`~/.config/systemd/user/seedst.service`)
- **Type**: `simple`
- **ExecStart**: Points to the Python executable inside the local `.venv`, ensuring dependencies are always available.
- **Restart**: `on-failure` (with 10s delay).

### Linger
- To allow the service to run at boot (before login) and persist after logout, the user must enable "lingering".
- Command: `loginctl enable-linger <username>`
- The `install` command attempts to guide the user through this.

## Security Model

### Trust Assumptions
1. **Mnemonic Security**: The BIP39 mnemonic is the "Root of Trust". Possession implies authorization.
2. **MQTT Broker**: Treated as "Hostile/Public". Adversaries can read all traffic.

### Encryption Details (AES-256-GCM)
- **Algorithm**: Advanced Encryption Standard (Galois/Counter Mode).
- **Key**: 256-bit key derived directly from the BIP39 seed.
- **Nonce**: A random 16-byte value generated for every message.
- **Benefits**:
  - **Confidentiality**: Only devices with the seed can decrypt the payload.
  - **Integrity**: GCM mode ensures the message hasn't been tampered with.
  - **Anonymity**: The MQTT topic is a hash of the seed. Without the seed, an observer cannot link the topic to a specific user, nor can they decrypt the payload to find Device IDs.

### Syncthing Connection
- SeedST handles the **control plane** (configuration and discovery).
- The **data plane** (file transfer) is handled by Syncthing's native TLS protocol.