"""
F.R.I.D.A.Y. — HUD GUI
A small Iron-Man-style heads-up display around friday_core.Friday.
The assistant (audio/clap/speech/Claude) runs on a background thread;
this file only touches Tkinter from the main thread, using root.after()
as the hand-off point — the standard thread-safe pattern for Tkinter.

Run with:  python friday_gui.py
"""

import threading
import queue
import math
import tkinter as tk
from tkinter import scrolledtext

from friday_core import Friday

# ── palette ──────────────────────────────
BG        = "#05070f"
PANEL_BG  = "#0b1020"
CORE_IDLE = "#1c7fa8"
CORE_LISTEN = "#00e08a"
CORE_THINK  = "#ffb020"
CORE_SPEAK  = "#00d9ff"
CORE_INTERVIEW = "#b892ff"
TEXT_MAIN = "#d7e6ff"
TEXT_DIM  = "#5c6b8a"
YOU_COLOR = "#8ad1ff"
FRIDAY_COLOR = "#00d9ff"
SYSTEM_COLOR = "#ffb020"

STATUS_COLORS = {
    "standby": (CORE_IDLE, "STANDBY — double clap or press Wake"),
    "listening": (CORE_LISTEN, "LISTENING..."),
    "thinking": (CORE_THINK, "THINKING..."),
    "speaking": (CORE_SPEAK, "SPEAKING..."),
}


class FridayGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("F.R.I.D.A.Y.")
        self.root.configure(bg=BG)
        self.root.geometry("560x680")
        self.root.minsize(480, 560)

        self.events = queue.Queue()  # background thread -> GUI thread
        self.pulse_phase = 0.0
        self.core_color = CORE_IDLE

        self._build_widgets()
        self._set_status_text("standby", "STANDBY — double clap or press Wake")

        self.friday = Friday(on_status=self._on_status_threadsafe, on_log=self._on_log_threadsafe)
        self.worker = threading.Thread(target=self.friday.start, daemon=True)
        self.worker.start()

        self._animate()
        self.root.after(80, self._drain_events)
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    # ── layout ──────────────────────────────
    def _build_widgets(self):
        title = tk.Label(self.root, text="F . R . I . D . A . Y .", fg=FRIDAY_COLOR, bg=BG,
                          font=("Consolas", 18, "bold"))
        title.pack(pady=(14, 0))

        subtitle = tk.Label(self.root, text="Powered by Claude AI — Built for Syed", fg=TEXT_DIM, bg=BG,
                             font=("Consolas", 9))
        subtitle.pack(pady=(0, 8))

        self.canvas = tk.Canvas(self.root, width=200, height=200, bg=BG, highlightthickness=0)
        self.canvas.pack(pady=4)

        self.status_label = tk.Label(self.root, text="", fg=TEXT_MAIN, bg=BG, font=("Consolas", 11, "bold"))
        self.status_label.pack(pady=(4, 10))

        # transcript
        log_frame = tk.Frame(self.root, bg=PANEL_BG, bd=1)
        log_frame.pack(fill="both", expand=True, padx=14, pady=(0, 10))

        self.log = scrolledtext.ScrolledText(
            log_frame, bg=PANEL_BG, fg=TEXT_MAIN, insertbackground=TEXT_MAIN,
            font=("Consolas", 10), wrap="word", bd=0, padx=10, pady=10, state="disabled"
        )
        self.log.pack(fill="both", expand=True)
        self.log.tag_config("you", foreground=YOU_COLOR)
        self.log.tag_config("friday", foreground=FRIDAY_COLOR)
        self.log.tag_config("system", foreground=SYSTEM_COLOR, font=("Consolas", 9, "italic"))

        # controls
        btn_frame = tk.Frame(self.root, bg=BG)
        btn_frame.pack(pady=(0, 14))

        self._make_button(btn_frame, "Wake", self._on_wake_clicked).grid(row=0, column=0, padx=5)
        self._make_button(btn_frame, "Mock Interview", self._on_interview_clicked).grid(row=0, column=1, padx=5)
        self._make_button(btn_frame, "Sleep", self._on_sleep_clicked).grid(row=0, column=2, padx=5)
        self._make_button(btn_frame, "Clear Memory", self._on_clear_clicked).grid(row=0, column=3, padx=5)

    def _make_button(self, parent, text, command):
        return tk.Button(
            parent, text=text, command=command, bg=PANEL_BG, fg=TEXT_MAIN,
            activebackground=CORE_IDLE, activeforeground=BG, relief="flat",
            font=("Consolas", 9, "bold"), padx=10, pady=6, cursor="hand2"
        )

    # ── animated core ──────────────────────────────
    def _animate(self):
        self.pulse_phase += 0.12
        base_r = 55
        r = base_r + 8 * math.sin(self.pulse_phase)
        cx, cy = 100, 100

        self.canvas.delete("all")
        self.canvas.create_oval(cx - r - 14, cy - r - 14, cx + r + 14, cy + r + 14,
                                 outline=self.core_color, width=1)
        self.canvas.create_oval(cx - r, cy - r, cx + r, cy + r,
                                 fill=self.core_color, outline="")
        self.canvas.create_oval(cx - r * 0.45, cy - r * 0.45, cx + r * 0.45, cy + r * 0.45,
                                 fill=BG, outline="")
        self.root.after(50, self._animate)

    # ── thread-safe hooks called from the Friday worker thread ──────────────────────────────
    def _on_status_threadsafe(self, status):
        self.events.put(("status", status))

    def _on_log_threadsafe(self, sender, text):
        self.events.put(("log", sender, text))

    def _drain_events(self):
        try:
            while True:
                event = self.events.get_nowait()
                if event[0] == "status":
                    self._apply_status(event[1])
                elif event[0] == "log":
                    self._append_log(event[1], event[2])
        except queue.Empty:
            pass
        self.root.after(80, self._drain_events)

    # ── UI updates (main thread only) ──────────────────────────────
    def _apply_status(self, status):
        if status.startswith("interview:"):
            progress = status.split(":", 1)[1]
            self.core_color = CORE_INTERVIEW
            self._set_status_text(status, f"MOCK INTERVIEW — question {progress}")
            return
        color, label = STATUS_COLORS.get(status, (CORE_IDLE, status.upper()))
        self.core_color = color
        self._set_status_text(status, label)

    def _set_status_text(self, _status, label):
        self.status_label.config(text=label)

    def _append_log(self, sender, text):
        self.log.config(state="normal")
        prefix = {"you": "YOU", "friday": "FRIDAY", "system": "•"}.get(sender, sender.upper())
        tag = sender if sender in ("you", "friday", "system") else "friday"
        self.log.insert("end", f"{prefix}: {text}\n\n", tag)
        self.log.see("end")
        self.log.config(state="disabled")

    # ── button handlers ──────────────────────────────
    def _on_wake_clicked(self):
        self.friday.request_wake()

    def _on_interview_clicked(self):
        self.friday.request_interview()

    def _on_sleep_clicked(self):
        self.friday.awake = False

    def _on_clear_clicked(self):
        self.friday.brain.reset_memory()
        self._append_log("system", "Memory cleared.")

    def _on_close(self):
        self.friday.stop()
        self.root.destroy()


def main():
    root = tk.Tk()
    FridayGUI(root)
    root.mainloop()


if __name__ == "__main__":
    main()
