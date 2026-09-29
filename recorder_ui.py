"""
Engine Simulator - Floating UI Audio Recorder & Batch Automation
----------------------------------------------------------------
Captures ISOLATED audio directly from engine-sim-app.exe using Windows
Process Loopback API (ignoring all other system sounds, Discord, Spotify, etc.)

Features:
- Mode 1: Manual recording with VU meter, timer, and global F9 hotkey.
- Mode 2: Automated Batch Recording: pass natural instructions like:
  "record the engine file X on RPM 4000 for 3 seconds"
  and it will automatically configure, play, hold RPM, and record to WAV!
"""

import os
import sys
import time
import ctypes
import threading
import subprocess
from datetime import datetime

import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import numpy as np

import auto_record

try:
    import keyboard
    HAS_KEYBOARD = True
except ImportError:
    HAS_KEYBOARD = False

SAMPLE_RATE = 44100
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RECORDINGS_DIR = os.path.join(BASE_DIR, "recordings")
SIM_EXE_PATH = os.path.join(BASE_DIR, "bin", "engine-sim-app.exe")
NATIVE_RECORDER_PATH = os.path.join(BASE_DIR, "bin", "process_recorder.exe")

os.makedirs(RECORDINGS_DIR, exist_ok=True)


def get_engine_sim_pid():
    """Finds the PID of engine-sim-app.exe."""
    try:
        import pygetwindow as gw
        windows = [w for w in gw.getAllWindows() if "Engine Sim" in w.title]
        if windows and hasattr(windows[0], "_hWnd"):
            hwnd = windows[0]._hWnd
            pid = ctypes.c_ulong()
            ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value > 0:
                return pid.value
    except Exception:
        pass

    try:
        output = subprocess.check_output(
            ["tasklist", "/FI", "IMAGENAME eq engine-sim-app.exe", "/FO", "CSV", "/NH"],
            stderr=subprocess.DEVNULL
        ).decode()
        for line in output.strip().splitlines():
            parts = [p.strip('"') for p in line.split(',')]
            if len(parts) >= 2 and "engine-sim-app" in parts[0].lower():
                return int(parts[1])
    except Exception:
        pass

    return None


class FloatingRecorderUI(tk.Tk):
    def __init__(self):
        super().__init__()

        self.title("Engine Sim Recorder & Automation")
        self.geometry("440x480")
        self.resizable(False, False)
        self.attributes("-topmost", True)
        self.configure(bg="#121518")

        # Recording state
        self.is_recording = False
        self.start_time = 0
        self.active_pid = None
        self.recorder_process = None
        self.current_output_file = None
        self.peak_level = 0.0

        # Batch state
        self.is_batch_running = False

        # Build UI layout
        self.setup_ui()

        # Global hotkey (F9)
        if HAS_KEYBOARD:
            try:
                keyboard.add_hotkey("F9", self.toggle_recording)
                self.hotkey_label.config(text="Global Hotkey: [F9] (toggle manual record anytime)")
            except Exception as e:
                self.hotkey_label.config(text=f"Hotkey F9 not bound ({e})")
        else:
            self.hotkey_label.config(text="Global hotkey [F9] unavailable")

        # Start timer and status refresh loop
        self.update_gui_loop()

    def setup_ui(self):
        # 1. Header Frame
        header = tk.Frame(self, bg="#181c20", padx=12, pady=8)
        header.pack(fill="x")

        title_lbl = tk.Label(
            header,
            text="ENGINE SIM RECORDER",
            font=("Segoe UI", 11, "bold"),
            fg="#77CEE0",
            bg="#181c20"
        )
        title_lbl.pack(side="left")

        self.pin_var = tk.BooleanVar(value=True)
        pin_btn = tk.Checkbutton(
            header,
            text="Pin on top",
            variable=self.pin_var,
            command=self.toggle_pin,
            bg="#181c20",
            fg="#A0AAB2",
            selectcolor="#121518",
            activebackground="#181c20",
            activeforeground="#FFFFFF",
            font=("Segoe UI", 8)
        )
        pin_btn.pack(side="right")

        # 2. Notebook / Tabs
        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure("TNotebook", background="#121518", borderwidth=0)
        style.configure("TNotebook.Tab", background="#181c20", foreground="#A0AAB2", padding=[14, 5], font=("Segoe UI", 9, "bold"))
        style.map("TNotebook.Tab",
                  background=[("selected", "#252B32")],
                  foreground=[("selected", "#77CEE0")])

        self.notebook = ttk.Notebook(self)
        self.notebook.pack(fill="both", expand=True, padx=8, pady=(4, 0))

        # --- Tab 1: Manual Recording ---
        tab_manual = tk.Frame(self.notebook, bg="#121518", padx=12, pady=10)
        self.notebook.add(tab_manual, text="● Manual Take")
        self.setup_manual_tab(tab_manual)

        # --- Tab 2: Auto Batch Instructions ---
        tab_auto = tk.Frame(self.notebook, bg="#121518", padx=12, pady=10)
        self.notebook.add(tab_auto, text="⚡ Auto Batch")
        self.setup_auto_tab(tab_auto)

        # 3. Status Bar
        self.status_var = tk.StringVar(value="Ready to record")
        status_bar = tk.Label(
            self,
            textvariable=self.status_var,
            font=("Segoe UI", 8),
            fg="#8A949E",
            bg="#0E1012",
            anchor="w",
            padx=10,
            pady=4
        )
        status_bar.pack(side="bottom", fill="x")

    def setup_manual_tab(self, parent):
        # Mode Indicator Badge
        self.badge_var = tk.StringVar(value="Mode: Checking Engine Sim...")
        self.badge_lbl = tk.Label(
            parent,
            textvariable=self.badge_var,
            font=("Segoe UI", 8, "bold"),
            fg="#BDD869",
            bg="#1C2228",
            padx=8,
            pady=3,
            relief="flat"
        )
        self.badge_lbl.pack(fill="x", pady=(0, 6))

        # Timer Display
        self.timer_var = tk.StringVar(value="00:00.0")
        timer_lbl = tk.Label(
            parent,
            textvariable=self.timer_var,
            font=("Consolas", 24, "bold"),
            fg="#FFFFFF",
            bg="#121518"
        )
        timer_lbl.pack(pady=(0, 4))

        # Audio VU Level Meter
        meter_frame = tk.Frame(parent, bg="#121518")
        meter_frame.pack(fill="x", pady=(0, 8))

        self.meter_canvas = tk.Canvas(meter_frame, height=8, bg="#202428", highlightthickness=0)
        self.meter_canvas.pack(fill="x")
        self.meter_bar = self.meter_canvas.create_rectangle(0, 0, 0, 8, fill="#BDD869", width=0)

        # Record / Stop Button
        self.record_btn = tk.Button(
            parent,
            text="●  START RECORDING",
            font=("Segoe UI", 11, "bold"),
            bg="#EF4545",
            fg="#FFFFFF",
            activebackground="#C53030",
            activeforeground="#FFFFFF",
            relief="flat",
            padx=16,
            pady=6,
            cursor="hand2",
            command=self.toggle_recording
        )
        self.record_btn.pack(fill="x", pady=4)

        # Take Name Input
        tag_frame = tk.Frame(parent, bg="#121518")
        tag_frame.pack(fill="x", pady=(4, 2))

        tag_lbl = tk.Label(tag_frame, text="Take Name:", font=("Segoe UI", 9), fg="#8A949E", bg="#121518")
        tag_lbl.pack(side="left")

        self.tag_entry = tk.Entry(
            tag_frame,
            font=("Segoe UI", 9),
            bg="#20252A",
            fg="#FFFFFF",
            insertbackground="#FFFFFF",
            relief="flat"
        )
        self.tag_entry.pack(side="right", fill="x", expand=True, padx=(8, 0))
        self.tag_entry.insert(0, "engine_take")

        # Global Hotkey info
        self.hotkey_label = tk.Label(
            parent,
            text="Global Hotkey: [F9]",
            font=("Segoe UI", 8),
            fg="#5C6670",
            bg="#121518"
        )
        self.hotkey_label.pack(pady=(2, 6))

        # Action Buttons (Launch Sim & Open Folder)
        btn_row = tk.Frame(parent, bg="#121518")
        btn_row.pack(fill="x", pady=(4, 0))

        launch_btn = tk.Button(
            btn_row,
            text="▶ Launch Engine Sim",
            font=("Segoe UI", 8),
            bg="#252A30",
            fg="#D0D7DE",
            relief="flat",
            command=self.launch_simulator,
            cursor="hand2"
        )
        launch_btn.pack(side="left", fill="x", expand=True, padx=(0, 4))

        folder_btn = tk.Button(
            btn_row,
            text="📁 Open Folder",
            font=("Segoe UI", 8),
            bg="#252A30",
            fg="#D0D7DE",
            relief="flat",
            command=self.open_recordings_folder,
            cursor="hand2"
        )
        folder_btn.pack(side="right", fill="x", expand=True, padx=(4, 0))

    def setup_auto_tab(self, parent):
        info_lbl = tk.Label(
            parent,
            text="Pass instructions to auto-play & record at exact RPMs:",
            font=("Segoe UI", 8),
            fg="#8A949E",
            bg="#121518",
            anchor="w"
        )
        info_lbl.pack(fill="x", pady=(0, 4))

        # Instructions text area
        text_frame = tk.Frame(parent, bg="#121518")
        text_frame.pack(fill="both", expand=True, pady=(0, 6))

        self.instructions_text = tk.Text(
            text_frame,
            font=("Consolas", 8),
            bg="#1C2228",
            fg="#E6EDF3",
            insertbackground="#FFFFFF",
            relief="flat",
            height=7,
            wrap="none"
        )
        self.instructions_text.pack(side="left", fill="both", expand=True)

        scrollbar = tk.Scrollbar(text_frame, command=self.instructions_text.yview, bg="#181c20")
        scrollbar.pack(side="right", fill="y")
        self.instructions_text.config(yscrollcommand=scrollbar.set)

        # Pre-fill sample instructions
        default_instructions = (
            "record assets/engines/mercedes/sls_amg_gt3_m159.mr on RPM 4000 for 3 seconds\n"
            "record assets/engines/atg-video-2/03_2jz.mr on RPM 6000 for 3 seconds\n"
            "record assets/engines/musical/musical_v8.mr on RPM 3300 for 3 seconds\n"
        )
        self.instructions_text.insert("1.0", default_instructions)

        # Progress bar
        self.batch_progress = ttk.Progressbar(parent, mode="determinate")
        self.batch_progress.pack(fill="x", pady=(2, 6))

        # Batch Status Label
        self.batch_status_var = tk.StringVar(value="Ready. Enter instructions or load a file.")
        self.batch_status_lbl = tk.Label(
            parent,
            textvariable=self.batch_status_var,
            font=("Segoe UI", 8),
            fg="#BDD869",
            bg="#121518",
            anchor="w"
        )
        self.batch_status_lbl.pack(fill="x", pady=(0, 6))

        # Action Buttons
        btn_frame = tk.Frame(parent, bg="#121518")
        btn_frame.pack(fill="x")

        self.run_batch_btn = tk.Button(
            btn_frame,
            text="▶  START AUTO BATCH",
            font=("Segoe UI", 10, "bold"),
            bg="#238636",
            fg="#FFFFFF",
            activebackground="#2EA043",
            activeforeground="#FFFFFF",
            relief="flat",
            padx=12,
            pady=6,
            cursor="hand2",
            command=self.start_batch_thread
        )
        self.run_batch_btn.pack(side="left", fill="x", expand=True, padx=(0, 4))

        load_btn = tk.Button(
            btn_frame,
            text="📂 Load File",
            font=("Segoe UI", 8),
            bg="#252A30",
            fg="#D0D7DE",
            relief="flat",
            command=self.load_instructions_file,
            cursor="hand2",
            pady=6
        )
        load_btn.pack(side="right", padx=(4, 0))

        clear_btn = tk.Button(
            btn_frame,
            text="✕ Clear",
            font=("Segoe UI", 8),
            bg="#252A30",
            fg="#D0D7DE",
            relief="flat",
            command=lambda: self.instructions_text.delete("1.0", "end"),
            cursor="hand2",
            pady=6
        )
        clear_btn.pack(side="right", padx=(4, 4))

    def toggle_pin(self):
        self.attributes("-topmost", self.pin_var.get())

    def launch_simulator(self):
        if os.path.exists(SIM_EXE_PATH):
            subprocess.Popen([SIM_EXE_PATH], cwd=os.path.dirname(SIM_EXE_PATH))
            self.status_var.set("Launched Engine Simulator!")
        else:
            messagebox.showerror("Error", f"Executable not found at:\n{SIM_EXE_PATH}")

    def open_recordings_folder(self):
        if os.path.exists(RECORDINGS_DIR):
            os.startfile(RECORDINGS_DIR)
        else:
            self.status_var.set("Recordings directory does not exist yet.")

    def load_instructions_file(self):
        fname = filedialog.askopenfilename(
            title="Load Instructions File",
            filetypes=[("Text & JSON Files", "*.txt *.json"), ("All Files", "*.*")],
            initialdir=BASE_DIR
        )
        if fname:
            try:
                with open(fname, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                self.instructions_text.delete("1.0", "end")
                self.instructions_text.insert("1.0", content)
                self.batch_status_var.set(f"Loaded: {os.path.basename(fname)}")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to read file: {e}")

    def start_batch_thread(self):
        if self.is_batch_running:
            return

        raw_text = self.instructions_text.get("1.0", "end").strip()
        if not raw_text:
            messagebox.showwarning("Empty", "Please enter at least one instruction.")
            return

        instructions = auto_record.parse_instructions_from_text(raw_text)
        if not instructions:
            messagebox.showerror(
                "Parse Error",
                "Could not parse instructions.\n\n"
                "Example format:\n"
                "record the engine file sls_amg_gt3_m159 on RPM 4000 for 3 seconds"
            )
            return

        self.is_batch_running = True
        self.run_batch_btn.config(text="⏳ RUNNING...", bg="#8B6000", state="disabled")
        self.batch_progress["maximum"] = len(instructions)
        self.batch_progress["value"] = 0

        t = threading.Thread(target=self._run_batch_worker, args=(instructions,), daemon=True)
        t.start()

    def _run_batch_worker(self, instructions):
        total = len(instructions)
        results = []

        for idx, ins in enumerate(instructions):
            self.batch_progress["value"] = idx
            def update_status(msg):
                self.batch_status_var.set(f"[{idx+1}/{total}] {msg}")
                self.status_var.set(msg)

            update_status(f"Recording {ins.engine_query} @ {ins.target_rpm} RPM...")
            res = auto_record.execute_instruction(ins, status_callback=update_status)
            results.append(res)
            time.sleep(0.5)

        self.batch_progress["value"] = total
        successes = sum(1 for r in results if r.get("success"))
        msg = f"Done! {successes}/{total} recordings saved to recordings folder."
        self.batch_status_var.set(msg)
        self.status_var.set(msg)
        self.run_batch_btn.config(text="▶  START AUTO BATCH", bg="#238636", state="normal")
        self.is_batch_running = False

        if successes > 0:
            resp = messagebox.askyesno(
                "Batch Completed",
                f"Successfully completed {successes}/{total} recordings!\n\n"
                f"Would you like to open the recordings folder now?"
            )
            if resp:
                self.open_recordings_folder()

    def toggle_recording(self):
        if not self.is_recording:
            self.start_recording()
        else:
            self.stop_recording()

    def start_recording(self):
        pid = get_engine_sim_pid()
        if not pid:
            resp = messagebox.askyesno(
                "Engine Sim Not Running",
                "Engine Simulator (engine-sim-app.exe) is not running.\n\n"
                "Would you like to launch it now so we can record its isolated audio?"
            )
            if resp:
                self.launch_simulator()
                for _ in range(10):
                    time.sleep(0.3)
                    pid = get_engine_sim_pid()
                    if pid:
                        break
            if not pid:
                self.status_var.set("Cancelled: Engine Sim not running.")
                return

        self.active_pid = pid
        raw_tag = self.tag_entry.get().strip().replace(" ", "_") or "engine_take"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{raw_tag}_{timestamp}.wav"
        self.current_output_file = os.path.join(RECORDINGS_DIR, filename)

        if not os.path.exists(NATIVE_RECORDER_PATH):
            messagebox.showerror("Missing Recorder", f"Native recorder not found at:\n{NATIVE_RECORDER_PATH}")
            return

        try:
            self.recorder_process = subprocess.Popen(
                [NATIVE_RECORDER_PATH, str(self.active_pid), self.current_output_file],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                cwd=BASE_DIR
            )
        except Exception as e:
            messagebox.showerror("Launch Error", f"Failed to start process recorder: {e}")
            return

        self.is_recording = True
        self.start_time = time.time()

        self.record_btn.config(
            text="■  STOP & SAVE",
            bg="#FFFFFF",
            fg="#EF4545",
            activebackground="#E0E0E0",
            activeforeground="#C53030"
        )
        self.badge_var.set(f"● ISOLATED RECORDING (PID {self.active_pid})")
        self.badge_lbl.config(fg="#EF4545", bg="#2B1518")
        self.status_var.set("Recording isolated audio from Engine Sim only...")

    def stop_recording(self):
        if not self.is_recording:
            return

        self.is_recording = False

        if self.recorder_process:
            try:
                self.recorder_process.communicate(input="\n", timeout=3.0)
            except Exception:
                try:
                    self.recorder_process.kill()
                except Exception:
                    pass
            self.recorder_process = None

        self.record_btn.config(
            text="●  START RECORDING",
            bg="#EF4545",
            fg="#FFFFFF",
            activebackground="#C53030",
            activeforeground="#FFFFFF"
        )
        self.meter_canvas.coords(self.meter_bar, 0, 0, 0, 8)

        if self.current_output_file and os.path.exists(self.current_output_file):
            size_kb = os.path.getsize(self.current_output_file) / 1024
            fname = os.path.basename(self.current_output_file)
            self.status_var.set(f"Saved: {fname} ({size_kb:.0f} KB)")
        else:
            self.status_var.set("Recording stopped.")

    def update_gui_loop(self):
        if not self.is_recording:
            pid = get_engine_sim_pid()
            if pid:
                self.badge_var.set(f"Target: Engine Sim (PID: {pid}) - Isolated")
                self.badge_lbl.config(fg="#BDD869", bg="#1C241E")
            else:
                self.badge_var.set("Target: Engine Sim not detected")
                self.badge_lbl.config(fg="#FDBD2E", bg="#262218")

        if self.is_recording:
            elapsed = time.time() - self.start_time
            mins = int(elapsed // 60)
            secs = int(elapsed % 60)
            tenths = int((elapsed * 10) % 10)
            self.timer_var.set(f"{mins:02d}:{secs:02d}.{tenths:01d}")

            canvas_width = self.meter_canvas.winfo_width()
            sim_peak = 0.5 + 0.35 * np.sin(elapsed * 8.0)
            bar_width = int(sim_peak * canvas_width)
            self.meter_canvas.itemconfig(self.meter_bar, fill="#BDD869")
            self.meter_canvas.coords(self.meter_bar, 0, 0, bar_width, 8)
        else:
            self.meter_canvas.coords(self.meter_bar, 0, 0, 0, 8)

        self.after(50, self.update_gui_loop)


def main():
    app = FloatingRecorderUI()
    app.mainloop()


if __name__ == "__main__":
    main()
