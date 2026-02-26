from __future__ import annotations

import argparse
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import requests
import tkinter as tk


# --- colors / theming ---
BG = "#111111"
FG = "#EAEAEA"
DIM = "#9AA0A6"
GREEN = "#3DDC84"
ORANGE = "#FF9F1A"
YELLOW = "#FFD60A"
RED = "#FF4D4F"


def color_for_percent(v: Optional[float]) -> str:
    if v is None:
        return DIM
    if v < 50:
        return GREEN
    if v < 80:
        return ORANGE
    return RED


def color_for_temp_c(v: Optional[float]) -> str:
    if v is None:
        return DIM
    if v < 70:
        return GREEN
    if v < 82:
        return YELLOW
    return RED


@dataclass
class AgentTarget:
    name: str
    url: str


def parse_agents(spec: str) -> List[AgentTarget]:
    out: List[AgentTarget] = []
    for part in [p.strip() for p in spec.split(",") if p.strip()]:
        if part.startswith("http://") or part.startswith("https://"):
            url = part.rstrip("/") + "/status"
            name = part
        else:
            hostport = part
            url = f"http://{hostport}/status"
            name = hostport
        out.append(AgentTarget(name=name, url=url))
    return out


class AgentPane:
    def __init__(self, parent: tk.Widget) -> None:
        self.frame = tk.Frame(parent, bg=BG)

        font = ("TkDefaultFont", 10)
        padx = 6

        self.host = tk.Label(self.frame, text="—", fg=FG, bg=BG, font=font, padx=padx)
        self.cpu = tk.Label(self.frame, text="CPU —", fg=DIM, bg=BG, font=font, padx=padx)
        self.mem = tk.Label(self.frame, text="MEM —", fg=DIM, bg=BG, font=font, padx=padx)
        self.gpu = tk.Label(self.frame, text="GPU —", fg=DIM, bg=BG, font=font, padx=padx)
        self.temp = tk.Label(self.frame, text="T —", fg=DIM, bg=BG, font=font, padx=padx)

        self.top_cpu = tk.Label(self.frame, text="C:—", fg=FG, bg=BG, font=font, padx=padx)
        self.top_mem = tk.Label(self.frame, text="M:—", fg=FG, bg=BG, font=font, padx=padx)
        self.top_gpu = tk.Label(self.frame, text="G:—", fg=FG, bg=BG, font=font, padx=padx)

        for w in (self.host, self.cpu, self.mem, self.gpu, self.temp, self.top_cpu, self.top_mem, self.top_gpu):
            w.pack(side="left")

        # subtle separator
        self.sep = tk.Frame(self.frame, bg="#222", width=2)
        self.sep.pack(side="left", fill="y", padx=(4, 4))

    def pack(self, **kwargs) -> None:
        self.frame.pack(**kwargs)

    def set_offline(self, label: str) -> None:
        self.host.config(text=label, fg=FG)
        for w in (self.cpu, self.mem, self.gpu, self.temp):
            w.config(text="—", fg=DIM)
        for w in (self.top_cpu, self.top_mem, self.top_gpu):
            w.config(text="—", fg=DIM)

    def update_from_payload(self, agent: AgentTarget, payload: Dict[str, Any], stale: bool) -> None:
        host = payload.get("host") or agent.name
        self.host.config(text=host, fg=FG if not stale else DIM)

        cpu = payload.get("cpu_percent")
        mem = (payload.get("mem") or {}).get("percent")

        # GPU: show max util/temp across GPUs
        gpus = payload.get("gpus") or []
        gpu_util = None
        gpu_temp = None
        try:
            utils = [g.get("utilization_gpu_percent") for g in gpus if g.get("utilization_gpu_percent") is not None]
            temps = [g.get("temperature_c") for g in gpus if g.get("temperature_c") is not None]
            gpu_util = max(utils) if utils else None
            gpu_temp = max(temps) if temps else None
        except Exception:
            pass

        if isinstance(cpu, (int, float)):
            self.cpu.config(text=f"CPU {cpu:.0f}%", fg=color_for_percent(float(cpu)))
        else:
            self.cpu.config(text="CPU —", fg=DIM)

        if isinstance(mem, (int, float)):
            self.mem.config(text=f"MEM {mem:.0f}%", fg=color_for_percent(float(mem)))
        else:
            self.mem.config(text="MEM —", fg=DIM)

        if isinstance(gpu_util, (int, float)):
            self.gpu.config(text=f"GPU {gpu_util:.0f}%", fg=color_for_percent(float(gpu_util)))
        else:
            self.gpu.config(text="GPU —", fg=DIM)

        if isinstance(gpu_temp, (int, float)):
            self.temp.config(text=f"T {gpu_temp:.0f}C", fg=color_for_temp_c(float(gpu_temp)))
        else:
            self.temp.config(text="T —", fg=DIM)

        def fmt_top(d: Dict[str, Any], prefix: str) -> Tuple[str, str]:
            n = d.get("name")
            v = d.get("value")
            if n is None or v is None:
                return (f"{prefix}:—", DIM)
            try:
                vf = float(v)
                return (f"{prefix}:{n} {vf:.0f}%", color_for_percent(vf))
            except Exception:
                return (f"{prefix}:{n}", FG)

        t = payload.get("top_cpu") or {}
        text, col = fmt_top(t, "C")
        self.top_cpu.config(text=text, fg=col)

        t = payload.get("top_mem") or {}
        text, col = fmt_top(t, "M")
        self.top_mem.config(text=text, fg=col)

        t = payload.get("top_gpu") or {}
        text, col = fmt_top(t, "G")
        self.top_gpu.config(text=text, fg=col)


class SparkMonBar:
    def __init__(self, agents: List[AgentTarget], height_px: int = 30) -> None:
        self.agents = agents
        self.height_px = height_px

        self.root = tk.Tk()
        self.root.title("sparkmon")

        # frameless bar
        self.root.overrideredirect(True)

        # allow closing via Esc
        self.root.bind("<Escape>", lambda _e: self.root.destroy())

        self.frame = tk.Frame(self.root, bg=BG)
        self.frame.pack(fill="both", expand=True)

        self.panes: List[AgentPane] = []
        for _ in agents:
            p = AgentPane(self.frame)
            p.pack(side="left", fill="both", expand=True)
            self.panes.append(p)

        self.data_lock = threading.Lock()
        self.latest: List[Tuple[float, Optional[Dict[str, Any]]]] = [(0.0, None) for _ in agents]

        self._position_bottom_bar(force=True)
        self._kick_poll_threads()
        self._ui_tick()
        self._geom_tick()

    def _position_bottom_bar(self, force: bool = False) -> None:
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        key = (sw, sh, self.height_px)
        if (not force) and getattr(self, "_last_geom_key", None) == key:
            return
        self._last_geom_key = key
        y = sh - self.height_px
        self.root.geometry(f"{sw}x{self.height_px}+0+{y}")

    def _kick_poll_threads(self) -> None:
        for idx, a in enumerate(self.agents):
            th = threading.Thread(target=self._poll_loop, args=(idx, a), daemon=True)
            th.start()

    def _poll_loop(self, idx: int, agent: AgentTarget) -> None:
        sess = requests.Session()
        while True:
            try:
                r = sess.get(agent.url, timeout=0.6)
                r.raise_for_status()
                payload = r.json()
            except Exception:
                payload = None
            with self.data_lock:
                self.latest[idx] = (time.time(), payload)
            time.sleep(1.0)

    def _ui_tick(self) -> None:
        with self.data_lock:
            latest = list(self.latest)

        now = time.time()
        for i, (ts, payload) in enumerate(latest):
            stale = payload is not None and (now - ts) > 2.5
            if payload is None:
                self.panes[i].set_offline(f"{self.agents[i].name} OFFLINE")
            else:
                self.panes[i].update_from_payload(self.agents[i], payload, stale=stale)

        self.root.after(250, self._ui_tick)

    def _geom_tick(self) -> None:
        # Geometry checks are cheap but don't need to run at UI framerate.
        self._position_bottom_bar(force=False)
        self.root.after(2000, self._geom_tick)

    def run(self) -> None:
        self.root.mainloop()


def main() -> None:
    ap = argparse.ArgumentParser(prog="sparkmon-display")
    ap.add_argument(
        "--agents",
        default="spark-9429:9000,spark-1914:9000",
        help="Comma-separated host:port or full URLs",
    )
    ap.add_argument("--height", type=int, default=30)
    args = ap.parse_args()

    agents = parse_agents(args.agents)
    app = SparkMonBar(agents=agents, height_px=args.height)
    app.run()


if __name__ == "__main__":
    main()
