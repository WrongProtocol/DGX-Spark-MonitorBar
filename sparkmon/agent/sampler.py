from __future__ import annotations

import os
import socket
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import psutil

from sparkmon.agent.nvml_gpu import NvmlSampler


def _proc_display_name(pid: int) -> Optional[str]:
    """Human-friendly process label.

    If the process is Python, try to show the script/module name instead of just "python".
    Examples:
      - python /path/to/server.py   -> server.py
      - python -m http.server       -> http.server
    """
    try:
        p = psutil.Process(pid)
        name = (p.name() or "").lower()

        if "python" in name:
            try:
                cmd = p.cmdline() or []
            except Exception:
                cmd = []

            # cmd[0] is interpreter; find first meaningful arg
            if len(cmd) >= 2:
                # module mode
                if cmd[1] == "-m" and len(cmd) >= 3:
                    return cmd[2]

                # skip common flags and take first non-flag
                for arg in cmd[1:]:
                    if not arg:
                        continue
                    if arg.startswith("-"):
                        continue
                    return os.path.basename(arg)

        # fallback: actual process name
        return p.name()
    except Exception:
        return None


def _top_process_by(get_value) -> Tuple[Optional[int], Optional[str], Optional[float]]:
    best = None  # (value, pid, name)
    for p in psutil.process_iter(attrs=["pid", "name"]):
        try:
            v = float(get_value(p))
        except Exception:
            continue
        if best is None or v > best[0]:
            best = (v, p.info.get("pid"), p.info.get("name"))
    if not best:
        return (None, None, None)
    return (int(best[1]) if best[1] is not None else None, best[2], float(best[0]))


@dataclass
class AgentConfig:
    sample_hz: float = 1.0
    top_every_s: float = 5.0


class Sampler:
    def __init__(self, config: AgentConfig | None = None) -> None:
        self.config = config or AgentConfig()
        self.nvml = NvmlSampler()
        self._last_top_t = 0.0
        self._top_cache: Dict[str, Any] = {
            "top_cpu": {"pid": None, "name": None, "value": None, "unit": "%"},
            "top_mem": {"pid": None, "name": None, "value": None, "unit": "%"},
            "top_gpu": {"pid": None, "name": None, "value": None, "unit": "%"},
        }

        # prime cpu percent measurement
        try:
            psutil.cpu_percent(interval=None)
        except Exception:
            pass

        # prime per-process cpu_percent deltas (used for "top CPU")
        self._top_cpu_primed = False

    def _update_top(self) -> None:
        now = time.time()
        if (now - self._last_top_t) < self.config.top_every_s:
            return
        self._last_top_t = now

        # Top CPU:
        # psutil needs two samples to compute cpu_percent deltas.
        # We do a single warm-up pass the first time, then on subsequent runs we
        # read deltas without sleeping.
        if not self._top_cpu_primed:
            try:
                for p in psutil.process_iter():
                    try:
                        p.cpu_percent(interval=None)
                    except Exception:
                        continue
            except Exception:
                pass
            self._top_cpu_primed = True
            cpu_pid, cpu_name, cpu_val = (None, None, None)
        else:
            cpu_pid, cpu_name, cpu_val = _top_process_by(lambda p: p.cpu_percent(interval=None))
            if cpu_pid is not None:
                cpu_name = _proc_display_name(cpu_pid) or cpu_name

        # Top MEM (single-pass)
        mem_pid, mem_name, mem_val = _top_process_by(lambda p: p.memory_percent())
        if mem_pid is not None:
            mem_name = _proc_display_name(mem_pid) or mem_name

        top_gpu = self.nvml.top_gpu_process(sample_window_ms=int(self.config.top_every_s * 1000))
        if top_gpu and top_gpu.get("pid") is not None:
            gp_pid = int(top_gpu["pid"])
            gp_name = _proc_display_name(gp_pid)
            gp_val = float(top_gpu.get("utilization_gpu_percent")) if top_gpu.get("utilization_gpu_percent") is not None else None
        else:
            gp_pid, gp_name, gp_val = None, None, None

        self._top_cache = {
            "top_cpu": {"pid": cpu_pid, "name": cpu_name, "value": cpu_val, "unit": "%"},
            "top_mem": {"pid": mem_pid, "name": mem_name, "value": mem_val, "unit": "%"},
            "top_gpu": {"pid": gp_pid, "name": gp_name, "value": gp_val, "unit": "%"},
        }

    def snapshot(self) -> Dict[str, Any]:
        self._update_top()

        vm = psutil.virtual_memory()
        cpu = psutil.cpu_percent(interval=None)

        gpus = self.nvml.gpus_snapshot()

        return {
            "ts": time.time(),
            "host": socket.gethostname(),
            "ip": self._best_ip_cached(),
            "uptime_s": time.time() - psutil.boot_time(),
            "cpu_percent": float(cpu),
            "mem": {
                "percent": float(vm.percent),
                "used_gb": float(vm.used) / (1024**3),
                "total_gb": float(vm.total) / (1024**3),
            },
            "gpus": gpus,  # list
            **self._top_cache,
        }

    def _best_ip_cached(self) -> Optional[str]:
        # Cache IP to avoid recomputing net interfaces every request.
        now = time.time()
        ttl_s = 60.0
        last_t = getattr(self, "_ip_cache_t", 0.0)
        if (now - last_t) < ttl_s:
            return getattr(self, "_ip_cache_v", None)

        ip = self._best_ip()
        setattr(self, "_ip_cache_t", now)
        setattr(self, "_ip_cache_v", ip)
        return ip

    def _best_ip(self) -> Optional[str]:
        # Lightweight best-effort. Prefer non-loopback IPv4.
        try:
            for _ifname, addrs in psutil.net_if_addrs().items():
                for a in addrs:
                    if getattr(a, "family", None) == socket.AF_INET:
                        ip = a.address
                        if ip and not ip.startswith("127."):
                            return ip
        except Exception:
            return None
        return None
