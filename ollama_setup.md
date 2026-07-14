# Running Ollama on an MSI Laptop (Windows) and Accessing it from macOS

This guide walks you through installing Ollama on Windows, pulling a suitable model, exposing it on the local network, and configuring the Hive project to use it.

---

## 1️⃣ Install Ollama on Windows

1. Download the Windows installer from:  
   https://ollama.com/download/windows (look for `OllamaSetup.exe`).
2. Run the installer – it adds `ollama` to your `PATH` and starts a background service listening on `localhost:11434`.
3. Verify installation:

```powershell
ollama --version   # e.g., "ollama version 0.6.2"
```

---

## 2️⃣ Pull a model suitable for Hive

The Hive pipeline uses the LLM only for the synthesis step. A good balance of quality and resource usage on a laptop is **Llama 3.1 8B**.

```powershell
ollama pull llama3.1:8b
```

*Optional alternatives* (if you have more GPU RAM or want to experiment):

```powershell
ollama pull nemotron-3-super-120b-a12b   # larger, needs strong GPU
ollama pull mistral                      # another solid 7B option
```

---

## 3️⃣ Make Ollama reachable from other machines on the LAN

By default Ollama binds only to `127.0.0.1:11434`. To expose it, set the `OLLAMA_HOST` environment variable before starting the service.

### 3.1 Find your laptop’s IPv4 address

```powershell
ipconfig | findstr /R /C:"IPv4 Address"
```

Example output:
```
IPv4 Address. . . . . . . . . . . : 192.168.1.42
```
Note this address (replace `192.168.1.42` with your actual IP).

### 3.2 Restart Ollama with the desired bind address

```powershell
# Replace <YOUR_IP> with the address you found (or use 0.0.0.0 to bind all interfaces)
$env:OLLAMA_HOST = "http://192.168.1.42:11434"
# To bind every interface:
# $env:OLLAMA_HOST = "http://0.0.0.0:11434"

# Stop the background service installed by the installer
net stop ollama

# Start it manually so it picks up the env var (runs in background)
ollama serve &
```

**Make the setting permanent (optional):**

```powershell
[Environment]::SetEnvironmentVariable('OLLAMA_HOST', $env:OLLAMA_HOST, 'Machine')
net stop ollama
net start ollama
```

### 3.3 Verify accessibility from another device

From any other machine on the same network (e.g., your Mac), run:

```bash
# Replace with your laptop's IP
curl http://192.168.1.42:11434/api/version
```

You should see a JSON response like `{"version":"0.6.2"}`.

If you get a timeout or “connection refused”, check:
- The IP address is correct.
- Windows Firewall isn’t blocking port 11434 (see next step).

---

## 4️⃣ (Optional) Open Windows Firewall for port 11434

If you experience connection‑timeout errors, allow inbound traffic on TCP 11434:

```powershell
New-NetFirewallRule -DisplayName "Ollama" -Direction Inbound -Protocol TCP -LocalPort 11434 -Action Allow
```

To remove the rule later:

```powershell
Remove-NetFirewallRule -DisplayName "Ollama"
```

---

## 5️⃣ Point your Hive code to the remote Ollama

On the Mac where you run `main.py`, set the `OLLAMA_HOST` environment variable to point at your laptop’s IP before invoking the script:

```bash
# In your Mac’s terminal (replace the IP with your MSI laptop’s)
export OLLAMA_HOST="http://192.168.1.42:11434"

# Run Hive – first run compiles, second run should skip
python3 main.py          # first run: compiles wiki/test-topic.md
python3 main.py          # second run: should output "Nothing changed, skipping."
```

To try the Claude provider instead, set `ANTHROPIC_API_KEY` (your Anthropic key) and pass `--provider claude`.

---

## 6️⃣ Quick sanity‑check from the Mac

```bash
# Test that the Mac can reach the model endpoint directly
curl -X POST http://192.168.1.42:11434/api/generate \
  -d '{"model":"llama3.1:8b","prompt":"Say hello in one sentence","stream":false}'
```

You should receive a JSON payload containing a `"response"` field with the model’s answer.

---

## 7️⃣ Performance tips for a laptop

| Tip | Why it helps |
|-----|--------------|
| **GPU‑enabled Ollama** (the Windows installer includes CUDA support if an NVIDIA GPU is present). | Offloads heavy matrix work to the GPU → lower latency. |
| **Keep the model loaded** – after the first `ollama run`, the model stays resident in VRAM. | Subsequent calls avoid the reload penalty. |
| **Limit concurrent requests** – Hive only sends one prompt at a time, but if you run multiple processes consider `OLLAMA_MAX_LOADED_MODELS=1`. | Prevents thrashing if GPU memory is limited. |
| **Monitor temperature** – sustained LLM loads can heat a laptop. Use a cooling pad or enable performance mode in MSI Dragon Center. | Avoids thermal throttling. |

---

## 8️⃣ Recap of the exact commands you’ll run

### On the MSI laptop (PowerShell)

```powershell
# 1) Verify installation
ollama --version

# 2) Pull the model (do this once)
ollama pull llama3.1:8b

# 3) Find your IP (note it down)
ipconfig | findstr /R /C:"IPv4 Address"

# 4) Set Ollama to listen on LAN (replace 192.168.1.42 with your IP)
$env:OLLAMA_HOST = "http://192.168.1.42:11434"
net stop ollama
ollama serve &   # leaves it running in the background

# 5) (Optional) Open firewall port
New-NetFirewallRule -DisplayName "Ollama" -Direction Inbound -Protocol TCP -LocalPort 11434 -Action Allow
```

### On your Mac (Terminal/Bash)

```bash
# Point to the laptop’s Ollama instance
export OLLAMA_HOST="http://192.168.1.42:11434"

# Run Hive – first run compiles, second run should skip
python3 main.py          # first run: compiles wiki/test-topic.md
python3 main.py          # second run: should output "Nothing changed, skipping."
```

---

### 🎉 You’re all set!

Your MSI laptop now serves an Ollama instance reachable by any machine on the same Wi‑Fi, and your Hive code will automatically use it via the `OLLAMA_HOST` environment variable. If you encounter any issues (connection refused, model not found, etc.), re‑run the verification steps above and double‑check the firewall/port binding.

Happy compiling! 🚀