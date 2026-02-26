from __future__ import annotations

import argparse
import threading
import time
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

import requests
import tkinter as tk


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


class SparkMonBar:
    def __init__(self, agents: List[AgentTarget], height_px: int = 30) -> None:
        self.agents = agents
        self.height_px = height_px
        self.root = tk.Tk()
        self.root.title("sparkmon")

        # frameless
        self.root.overrideredirect(True)

        # allow closing via Esc
        self.root.bind("<Escape>", lambda _e: self.root.destroy())

        self.frame = tk.Frame(self.root, bg="#111")
        self.frame.pack(fill="both", expand=True)

        self.labels: List[tk.Label] = []
        for _ in agents:
            lbl = tk.Label(
                self.frame,
                text="…",
                fg="#eee",
                bg="#111",
                font=("TkDefaultFont", 10),
                padx=10,
                pady=0,
                anchor="w",
                justify="left",
            )
            lbl.pack(side="left", fill="both", expand=True)
            self.labels.append(lbl)

        self.data_lock = threading.Lock()
        self.latest: List[Tuple[float, Optional[Dict[str, Any]]]] = [(0.0, None) for _ in agents]

        self._position_bottom_bar()
        self._kick_poll_threads()
        self._ui_tick()

    def _position_bottom_bar(self) -> None:
        self.root.update_idletasks()
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
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

    def _fmt_agent(self, agent: AgentTarget, payload: Optional[Dict[str, Any]]) -> str:
        if not payload:
            return f"{agent.name}  |  OFFLINE"

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

        top_cpu = payload.get("top_cpu") or {}
        top_mem = payload.get("top_mem") or {}
        top_gpu = payload.get("top_gpu") or {}

        def fmt_top(d: Dict[str, Any], label: str) -> str:
            n = d.get("name")
            v = d.get("value")
            if n is None or v is None:
                return f"{label}:—"
            try:
                return f"{label}:{n} {v:.0f}%"
            except Exception:
                return f"{label}:{n}"

        parts = [
            f"{payload.get('host', agent.name)}",
            f"CPU {cpu:.0f}%" if isinstance(cpu, (int, float)) else "CPU —",
            f"MEM {mem:.0f}%" if isinstance(mem, (int, float)) else "MEM —",
            f"GPU {gpu_util:.0f}%" if isinstance(gpu_util, (int, float)) else "GPU —",
            f"T {gpu_temp:.0f}C" if isinstance(gpu_temp, (int, float)) else "T —",
            fmt_top(top_cpu, "C"),
            fmt_top(top_mem, "M"),
            fmt_top(top_gpu, "G"),
        ]
        return "  |  ".join(parts)

    def _ui_tick(self) -> None:
        with self.data_lock:
            latest = list(self.latest)

        for i, (ts, payload) in enumerate(latest):
            txt = self._fmt_agent(self.agents[i], payload)
            # stale indicator
            if payload and (time.time() - ts) > 2.5:
                txt = txt + "  |  STALE"
            self.labels[i].config(text=txt)

        # re-position in case resolution changes
        self._position_bottom_bar()
        self.root.after(250, self._ui_tick)

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
