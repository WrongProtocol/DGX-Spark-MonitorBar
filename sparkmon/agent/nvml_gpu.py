from __future__ import annotations

import time
from typing import Any, Dict, List, Optional


def _try_import_nvml():
    try:
        import pynvml  # type: ignore

        return pynvml
    except Exception:
        return None


class NvmlSampler:
    """Best-effort NVML sampler.

    Supports:
      - GPU utilization %
      - GPU temperature (C)
      - Top GPU process by SM utilization (when NVML exposes per-process util samples)

    Notes:
      - On unified memory systems, VRAM metrics may be meaningless; we don't rely on them.
      - NVML per-process utilization is not guaranteed on all driver/NVML versions.
    """

    def __init__(self) -> None:
        self.pynvml = _try_import_nvml()
        self.initialized = False
        self.last_proc_util_ts_us: Optional[int] = None

    def init(self) -> bool:
        if not self.pynvml:
            return False
        if self.initialized:
            return True
        try:
            self.pynvml.nvmlInit()
            self.initialized = True
            # start from "now" so we don't ask for huge history
            self.last_proc_util_ts_us = int(time.time() * 1_000_000)
            return True
        except Exception:
            self.initialized = False
            return False

    def shutdown(self) -> None:
        if not (self.pynvml and self.initialized):
            return
        try:
            self.pynvml.nvmlShutdown()
        except Exception:
            pass
        self.initialized = False

    def gpus_snapshot(self) -> List[Dict[str, Any]]:
        if not self.init():
            return []

        out: List[Dict[str, Any]] = []
        try:
            count = self.pynvml.nvmlDeviceGetCount()
        except Exception:
            return []

        for i in range(count):
            try:
                h = self.pynvml.nvmlDeviceGetHandleByIndex(i)
                name = self.pynvml.nvmlDeviceGetName(h)
                if isinstance(name, bytes):
                    name = name.decode("utf-8", "ignore")

                util = None
                try:
                    u = self.pynvml.nvmlDeviceGetUtilizationRates(h)
                    util = float(getattr(u, "gpu", None))
                except Exception:
                    util = None

                temp = None
                try:
                    temp = float(self.pynvml.nvmlDeviceGetTemperature(h, self.pynvml.NVML_TEMPERATURE_GPU))
                except Exception:
                    temp = None

                out.append(
                    {
                        "index": i,
                        "name": name,
                        "utilization_gpu_percent": util,
                        "temperature_c": temp,
                    }
                )
            except Exception:
                continue

        return out

    def top_gpu_process(self, sample_window_ms: int = 5000) -> Optional[Dict[str, Any]]:
        """Return top process by SM utilization (%) across all GPUs.

        Best-effort: requires nvmlDeviceGetProcessUtilization.
        """
        if not self.init():
            return None

        # NVML expects a start timestamp in microseconds
        now_us = int(time.time() * 1_000_000)
        start_us = self.last_proc_util_ts_us or (now_us - sample_window_ms * 1000)

        best = None  # (smUtil, pid, gpu_index)

        try:
            count = self.pynvml.nvmlDeviceGetCount()
        except Exception:
            return None

        for gi in range(count):
            try:
                h = self.pynvml.nvmlDeviceGetHandleByIndex(gi)
                # API exists?
                get_proc_util = getattr(self.pynvml, "nvmlDeviceGetProcessUtilization", None)
                if not get_proc_util:
                    continue

                samples = get_proc_util(h, start_us)
                # samples: list of structs with pid, smUtil, memUtil, encUtil, decUtil, timeStamp
                for s in samples or []:
                    sm = getattr(s, "smUtil", None)
                    pid = getattr(s, "pid", None)
                    if sm is None or pid is None:
                        continue
                    smf = float(sm)
                    if (best is None) or (smf > best[0]):
                        best = (smf, int(pid), gi)
            except Exception:
                continue

        self.last_proc_util_ts_us = now_us

        if not best:
            return None

        smf, pid, gi = best
        # process name is resolved in the agent via psutil; here we return pid + value
        return {"pid": pid, "gpu_index": gi, "utilization_gpu_percent": smf}
