from __future__ import annotations

import os
import socket
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

import psutil

from sparkmon.agent.nvml_gpu import NvmlSampler


def _proc_name(pid: int) -> Optional[str]:
    try:
        p = psutil.Process(pid)
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

    def _update_top(self) -> None:
        now = time.time()
        if (now - self._last_top_t) < self.config.top_every_s:
            return
        self._last_top_t = now

        # Top CPU: percent over very short interval. Avoid heavy per-proc sampling.
        # We do a quick per-proc cpu_percent(None) which uses cached deltas.
        try:
            for p in psutil.process_iter():
                try:
                    p.cpu_percent(interval=None)
                except Exception:
                    continue
            time.sleep(0.05)
        except Exception:
            pass

        cpu_pid, cpu_name, cpu_val = _top_process_by(lambda p: p.cpu_percent(interval=None))
        mem_pid, mem_name, mem_val = _top_process_by(lambda p: p.memory_percent())

        top_gpu = self.nvml.top_gpu_process(sample_window_ms=int(self.config.top_every_s * 1000))
        if top_gpu and top_gpu.get("pid") is not None:
            gp_pid = int(top_gpu["pid"])
            gp_name = _proc_name(gp_pid)
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
            "ip": self._best_ip(),
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

    def _best_ip(self) -> Optional[str]:
        # Lightweight best-effort. Prefer non-loopback IPv4.
        try:
            for ifname, addrs in psutil.net_if_addrs().items():
                for a in addrs:
                    if getattr(a, "family", None) == socket.AF_INET:
                        ip = a.address
                        if ip and not ip.startswith("127."):
                            return ip
        except Exception:
            return None
        return None
