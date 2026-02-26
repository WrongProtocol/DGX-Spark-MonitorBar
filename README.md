# sparkmon

Minimal, resource-efficient health monitor for the DGX Spark boxes.

## Components

- **Agent** (runs on each Spark box): terminal app that samples local system metrics and serves them over HTTP.
- **Display** (runs on your desktop): tiny Tkinter bar that polls agents and displays live metrics.

## Quick start (dev)

### Agent (on each Spark box)

```bash
cd ~/sparkmon
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m sparkmon.agent --host 0.0.0.0 --port 9000
```

Test:

```bash
curl http://127.0.0.1:9000/status
```

### Display (desktop)

```bash
cd ~/sparkmon
source .venv/bin/activate
python -m sparkmon.display --agents spark-9429:9000,spark-1914:9000
```

## Notes

- GPU stats are best-effort via NVML (pynvml). If NVML is unavailable, GPU fields return `null`.
- “Top GPU process” is computed via NVML per-process utilization samples when supported; otherwise it may be `null`.
