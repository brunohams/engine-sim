import os
import sys
import time
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import math
import engine_recorder_backend as backend

class EngineRecorderApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Engine Simulator - Automated Audio Recorder")
        self.root.geometry("920x860")
        self.root.minsize(840, 720)

        # Color palette (Deep Midnight Slate - Clean High Contrast)
        self.bg_color = "#0f141c"        # Deep sleek dark background
        self.panel_bg = "#18202e"       # Card / container background
        self.panel_sub = "#121824"      # Inner container background (checkbox area)
        self.border_color = "#2a374d"   # Card border
        self.fg_color = "#f1f5f9"       # High contrast bright white/slate
        self.fg_sub = "#94a3b8"         # Subdued slate text
        self.accent_color = "#38bdf8"   # Vibrant sky cyan
        self.input_bg = "#222c3d"       # Clearly visible textbox/combobox background
        self.input_fg = "#ffffff"       # Crisp white text in all inputs
        self.btn_bg = "#283448"         # Clean slate button
        self.btn_hover = "#384762"      # Button hover
        self.btn_record_bg = "#22c55e"  # Vivid Emerald green
        self.btn_stop_bg = "#ef4444"    # Vivid Red

        self.root.configure(bg=self.bg_color)

        # Style configuration
        self.style = ttk.Style()
        try:
            self.style.theme_use("clam")
        except Exception:
            pass

        # Configure popdown listbox (the dropdown list itself when clicked!)
        self.root.option_add('*TCombobox*Listbox.background', self.input_bg)
        self.root.option_add('*TCombobox*Listbox.foreground', '#ffffff')
        self.root.option_add('*TCombobox*Listbox.selectBackground', '#0284c7')
        self.root.option_add('*TCombobox*Listbox.selectForeground', '#ffffff')
        self.root.option_add('*TCombobox*Listbox.font', ('Segoe UI', 10))

        # Base style
        self.style.configure(".", background=self.bg_color, foreground=self.fg_color, font=("Segoe UI", 10))
        self.style.configure("TLabel", background=self.bg_color, foreground=self.fg_color)
        self.style.configure("TFrame", background=self.bg_color)

        # Labelframe
        self.style.configure("TLabelframe", background=self.bg_color, bordercolor=self.border_color)
        self.style.configure("TLabelframe.Label", background=self.bg_color, foreground=self.accent_color, font=("Segoe UI", 10, "bold"))

        # Buttons
        self.style.configure("TButton", 
            background=self.btn_bg, 
            foreground="#ffffff", 
            bordercolor=self.border_color,
            focuscolor=self.accent_color,
            font=("Segoe UI", 9, "bold"), 
            padding=(10, 4)
        )
        self.style.map("TButton",
            background=[("active", self.btn_hover), ("pressed", "#1b2433"), ("disabled", "#141a24")],
            foreground=[("disabled", "#64748b")]
        )

        # Comboboxes (HIGH CONTRAST & VERY READABLE)
        self.style.configure("TCombobox",
            fieldbackground=self.input_bg,
            background=self.btn_bg,
            foreground="#ffffff",
            arrowcolor=self.accent_color,
            bordercolor=self.border_color,
            lightcolor=self.border_color,
            darkcolor=self.border_color,
            padding=4
        )
        self.style.map("TCombobox",
            fieldbackground=[("readonly", self.input_bg), ("disabled", "#141a24")],
            foreground=[("readonly", "#ffffff"), ("disabled", "#64748b")],
            background=[("readonly", self.btn_bg), ("disabled", "#141a24")],
            arrowcolor=[("readonly", self.accent_color), ("disabled", "#64748b")]
        )

        # Entries (HIGH CONTRAST & VERY READABLE)
        self.style.configure("TEntry",
            fieldbackground=self.input_bg,
            foreground="#ffffff",
            insertcolor=self.accent_color,
            bordercolor=self.border_color,
            lightcolor=self.border_color,
            darkcolor=self.border_color,
            padding=4
        )
        self.style.map("TEntry",
            fieldbackground=[("disabled", "#141a24")],
            foreground=[("disabled", "#64748b")]
        )

        # Progress bar
        self.style.configure("TProgressbar",
            troughcolor=self.panel_sub,
            background=self.accent_color,
            bordercolor=self.border_color
        )

        self.engines_list = []
        self.current_engine_specs = None
        self.rpm_vars = {}  # {rpm_int: tk.BooleanVar}
        self.runner = None

        self._build_ui()
        self._load_engines()

        # Handle window close
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self):
        main_container = ttk.Frame(self.root, padding="14")
        main_container.pack(fill=tk.BOTH, expand=True)

        # 1. Header
        header_frame = ttk.Frame(main_container)
        header_frame.pack(fill=tk.X, pady=(0, 8))
        title_lbl = tk.Label(header_frame, text="Engine Simulator Audio Automator", 
                             font=("Segoe UI", 16, "bold"), bg=self.bg_color, fg=self.accent_color)
        title_lbl.pack(side=tk.LEFT)
        subtitle_lbl = tk.Label(header_frame, text="Auto-record On/Off throttle audio, Idle, Max RPM, Startup & Shutdown.", 
                                font=("Segoe UI", 9), bg=self.bg_color, fg=self.fg_sub)
        subtitle_lbl.pack(side=tk.LEFT, padx=14, pady=(5, 0))

        # 2. Engine Selection Section
        engine_group = ttk.LabelFrame(main_container, text=" 1. Select Engine (.mr file) ", padding="10")
        engine_group.pack(fill=tk.X, pady=(0, 6))

        sel_row = ttk.Frame(engine_group)
        sel_row.pack(fill=tk.X, pady=(0, 6))

        ttk.Label(sel_row, text="Detected Engines:").pack(side=tk.LEFT, padx=(0, 8))
        self.engine_combo = ttk.Combobox(sel_row, state="readonly", width=55)
        self.engine_combo.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))
        self.engine_combo.bind("<<ComboboxSelected>>", self._on_engine_selected)

        browse_btn = ttk.Button(sel_row, text="Browse .mr...", command=self._on_browse_engine)
        browse_btn.pack(side=tk.LEFT)

        # Info card
        self.info_card = tk.Frame(engine_group, bg=self.panel_bg, padx=12, pady=6, bd=1, relief=tk.SOLID, highlightbackground=self.border_color)
        self.info_card.pack(fill=tk.X, pady=(2, 0))
        
        self.engine_name_lbl = tk.Label(self.info_card, text="No engine selected", font=("Segoe UI", 12, "bold"), 
                                        bg=self.panel_bg, fg=self.accent_color)
        self.engine_name_lbl.pack(anchor="w")

        self.engine_stats_lbl = tk.Label(self.info_card, text="Redline: - | Idle / Dyno Min: - | File: -", 
                                         font=("Segoe UI", 9), bg=self.panel_bg, fg=self.fg_color)
        self.engine_stats_lbl.pack(anchor="w", pady=(2, 0))

        # 3. Special Takes & Throttle Transients Section
        special_group = ttk.LabelFrame(main_container, text=" 2. Special Engine Audio Takes & Transients ", padding="10")
        special_group.pack(fill=tk.X, pady=(0, 6))

        spec_row = ttk.Frame(special_group)
        spec_row.pack(fill=tk.X)

        self.startup_var = tk.BooleanVar(value=True)
        self.idle_var = tk.BooleanVar(value=True)
        self.max_rev_var = tk.BooleanVar(value=True)
        self.shutdown_var = tk.BooleanVar(value=True)

        cb_startup = tk.Checkbutton(spec_row, text="Startup (Cranking / Turn On)",
                                    variable=self.startup_var, font=("Segoe UI", 9, "bold"),
                                    bg=self.bg_color, fg="#38bdf8", selectcolor=self.input_bg,
                                    activebackground=self.bg_color, activeforeground="#38bdf8",
                                    command=self._update_selected_count)
        cb_startup.pack(side=tk.LEFT, padx=(0, 18))

        cb_idle = tk.Checkbutton(spec_row, text="Idle (Seamless Loop)",
                                 variable=self.idle_var, font=("Segoe UI", 9, "bold"),
                                 bg=self.bg_color, fg="#4ade80", selectcolor=self.input_bg,
                                 activebackground=self.bg_color, activeforeground="#4ade80",
                                 command=self._update_selected_count)
        cb_idle.pack(side=tk.LEFT, padx=(0, 18))

        cb_max_rev = tk.Checkbutton(spec_row, text="Max RPM Revving (Full Throttle Loop)",
                                    variable=self.max_rev_var, font=("Segoe UI", 9, "bold"),
                                    bg=self.bg_color, fg="#f472b6", selectcolor=self.input_bg,
                                    activebackground=self.bg_color, activeforeground="#f472b6",
                                    command=self._update_selected_count)
        cb_max_rev.pack(side=tk.LEFT, padx=(0, 18))

        cb_shutdown = tk.Checkbutton(spec_row, text="Shutdown (Turn Off / Stop)",
                                     variable=self.shutdown_var, font=("Segoe UI", 9, "bold"),
                                     bg=self.bg_color, fg="#fb923c", selectcolor=self.input_bg,
                                     activebackground=self.bg_color, activeforeground="#fb923c",
                                     command=self._update_selected_count)
        cb_shutdown.pack(side=tk.LEFT)

        # Transients Row: Blips & Lifts (One-shot, no loop)
        transient_row = ttk.Frame(special_group)
        transient_row.pack(fill=tk.X, pady=(8, 0))

        self.blip_var = tk.BooleanVar(value=True)
        self.lift_var = tk.BooleanVar(value=True)

        cb_blip = tk.Checkbutton(transient_row, text="Blip (0% → 100% Kick)",
                                 variable=self.blip_var, font=("Segoe UI", 9, "bold"),
                                 bg=self.bg_color, fg="#38bdf8", selectcolor=self.input_bg,
                                 activebackground=self.bg_color, activeforeground="#38bdf8",
                                 command=self._update_selected_count)
        cb_blip.pack(side=tk.LEFT, padx=(0, 18))

        cb_lift = tk.Checkbutton(transient_row, text="Lift (100% → 0% Drop)",
                                 variable=self.lift_var, font=("Segoe UI", 9, "bold"),
                                 bg=self.bg_color, fg="#facc15", selectcolor=self.input_bg,
                                 activebackground=self.bg_color, activeforeground="#facc15",
                                 command=self._update_selected_count)
        cb_lift.pack(side=tk.LEFT, padx=(0, 18))

        ttk.Label(transient_row, text="Blip/Lift Interval:").pack(side=tk.LEFT, padx=(0, 6))
        self.blip_lift_step_combo = ttk.Combobox(
            transient_row,
            values=["1,000 RPM", "2,000 RPM (Default)", "3,000 RPM", "Same as Stepped RPMs", "Selected RPMs Only"],
            state="readonly", width=22
        )
        self.blip_lift_step_combo.current(1)
        self.blip_lift_step_combo.pack(side=tk.LEFT, padx=(0, 10))
        self.blip_lift_step_combo.bind("<<ComboboxSelected>>", lambda e: self._update_selected_count())

        self.blip_lift_info_lbl = tk.Label(transient_row, text="", bg=self.bg_color, fg="#94a3b8", font=("Segoe UI", 8))
        self.blip_lift_info_lbl.pack(side=tk.LEFT)

        # 4. RPM Values Selection Section
        rpm_group = ttk.LabelFrame(main_container, text=" 3. Stepped Engine RPM Values to Record (Above Idle) ", padding="10")
        rpm_group.pack(fill=tk.BOTH, expand=True, pady=(0, 6))

        rpm_ctrl_row = ttk.Frame(rpm_group)
        rpm_ctrl_row.pack(fill=tk.X, pady=(0, 6))

        ttk.Label(rpm_ctrl_row, text="Step Increment:").pack(side=tk.LEFT, padx=(0, 6))
        self.step_combo = ttk.Combobox(rpm_ctrl_row, values=["500 RPM", "1,000 RPM (Default)", "1,500 RPM", "2,000 RPM"], 
                                       state="readonly", width=18)
        self.step_combo.current(1)
        self.step_combo.pack(side=tk.LEFT, padx=(0, 14))
        self.step_combo.bind("<<ComboboxSelected>>", self._on_step_changed)

        select_all_btn = ttk.Button(rpm_ctrl_row, text="Select All", command=self._select_all_rpms)
        select_all_btn.pack(side=tk.LEFT, padx=(0, 5))

        deselect_all_btn = ttk.Button(rpm_ctrl_row, text="Deselect All", command=self._deselect_all_rpms)
        deselect_all_btn.pack(side=tk.LEFT, padx=(0, 14))

        self.selected_count_lbl = tk.Label(rpm_ctrl_row, text="0 RPMs selected", bg=self.bg_color, fg=self.accent_color, font=("Segoe UI", 9, "bold"))
        self.selected_count_lbl.pack(side=tk.LEFT)

        # Scrollable Frame for RPM Checkboxes
        canvas_frame = tk.Frame(rpm_group, bg=self.panel_sub, bd=1, relief=tk.SOLID, highlightbackground=self.border_color)
        canvas_frame.pack(fill=tk.BOTH, expand=True)

        self.canvas = tk.Canvas(canvas_frame, bg=self.panel_sub, highlightthickness=0)
        scrollbar = ttk.Scrollbar(canvas_frame, orient=tk.VERTICAL, command=self.canvas.yview)
        self.checkboxes_container = tk.Frame(self.canvas, bg=self.panel_sub)

        self.checkboxes_container.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas_window = self.canvas.create_window((0, 0), window=self.checkboxes_container, anchor="nw")
        self.canvas.configure(yscrollcommand=scrollbar.set)

        self.canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=4, pady=4)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

        # 5. Recording & Audio Processing Options Section
        settings_group = ttk.LabelFrame(main_container, text=" 4. Recording & Audio Looper Options ", padding="10")
        settings_group.pack(fill=tk.X, pady=(0, 6))

        # Row 1: Throttle Mode & Settle Delay & Seamless Loop
        opt_row1 = ttk.Frame(settings_group)
        opt_row1.pack(fill=tk.X, pady=(0, 4))

        ttk.Label(opt_row1, text="Throttle Mode:").pack(side=tk.LEFT, padx=(0, 6))
        self.throttle_mode_combo = ttk.Combobox(
            opt_row1, 
            values=["Both On & Off (_On / _Off)", "On-Throttle Only (_On)", "Off-Throttle Only (_Off)"],
            state="readonly", width=25
        )
        self.throttle_mode_combo.current(0)
        self.throttle_mode_combo.pack(side=tk.LEFT, padx=(0, 16))
        self.throttle_mode_combo.bind("<<ComboboxSelected>>", lambda e: self._update_selected_count())

        ttk.Label(opt_row1, text="Settle Delay (s):").pack(side=tk.LEFT, padx=(0, 6))
        self.settle_delay_var = tk.StringVar(value="1.5")
        settle_entry = ttk.Entry(opt_row1, textvariable=self.settle_delay_var, width=5)
        settle_entry.pack(side=tk.LEFT, padx=(0, 16))

        ttk.Label(opt_row1, text="Duration per Take (s):").pack(side=tk.LEFT, padx=(0, 6))
        self.duration_var = tk.StringVar(value="3.0")
        dur_entry = ttk.Entry(opt_row1, textvariable=self.duration_var, width=5)
        dur_entry.pack(side=tk.LEFT, padx=(0, 16))

        self.loop_var = tk.BooleanVar(value=True)
        loop_cb = tk.Checkbutton(opt_row1, text="Generate Perfect Seamless Loops (Zero clicks)",
                                 variable=self.loop_var, font=("Segoe UI", 9, "bold"),
                                 bg=self.bg_color, fg="#4ade80", selectcolor=self.input_bg, activebackground=self.bg_color)
        loop_cb.pack(side=tk.LEFT)

        # Row 2: Output Directory
        opt_row2 = ttk.Frame(settings_group)
        opt_row2.pack(fill=tk.X, pady=(4, 0))

        ttk.Label(opt_row2, text="Output Directory:").pack(side=tk.LEFT, padx=(0, 6))
        self.out_dir_var = tk.StringVar(value=os.path.abspath("recordings"))
        out_entry = ttk.Entry(opt_row2, textvariable=self.out_dir_var, width=40)
        out_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 6))

        browse_out_btn = ttk.Button(opt_row2, text="Browse...", command=self._on_browse_output_dir)
        browse_out_btn.pack(side=tk.LEFT, padx=(0, 6))

        open_out_btn = ttk.Button(opt_row2, text="Open Folder", command=self._on_open_output_dir)
        open_out_btn.pack(side=tk.LEFT)

        # 6. Controls & Live Progress Section
        progress_group = ttk.LabelFrame(main_container, text=" 5. Progress & Controls ", padding="10")
        progress_group.pack(fill=tk.X, pady=(0, 0))

        act_row = ttk.Frame(progress_group)
        act_row.pack(fill=tk.X, pady=(0, 6))

        self.record_btn = tk.Button(act_row, text="RECORD SELECTED AUDIO TAKES", font=("Segoe UI", 11, "bold"),
                                    bg=self.btn_record_bg, fg="#052e16", activebackground="#4ade80",
                                    padx=18, pady=6, bd=0, cursor="hand2", command=self._start_recording)
        self.record_btn.pack(side=tk.LEFT, padx=(0, 12))

        self.stop_btn = tk.Button(act_row, text="STOP / CANCEL", font=("Segoe UI", 11, "bold"),
                                  bg=self.btn_stop_bg, fg="#ffffff", activebackground="#f87171",
                                  padx=18, pady=6, bd=0, cursor="hand2", state=tk.DISABLED, command=self._stop_recording)
        self.stop_btn.pack(side=tk.LEFT)

        self.status_lbl = tk.Label(act_row, text="Ready", font=("Segoe UI", 10, "bold"), bg=self.bg_color, fg=self.accent_color)
        self.status_lbl.pack(side=tk.RIGHT, padx=6)

        # Progress bar
        self.progress_bar = ttk.Progressbar(progress_group, orient=tk.HORIZONTAL, mode='determinate')
        self.progress_bar.pack(fill=tk.X, pady=(0, 6))

        # Log Output Box
        self.log_box = tk.Text(progress_group, height=5, bg="#0b0e14", fg="#7dd3fc", font=("Consolas", 10),
                               bd=1, relief=tk.SOLID, highlightbackground=self.border_color, state=tk.NORMAL)
        self.log_box.pack(fill=tk.X)
        self.log_box.insert(tk.END, "Engine Simulator Audio Automator ready.\n")
        self.log_box.config(state=tk.DISABLED)

    def _on_mousewheel(self, event):
        self.canvas.yview_scroll(int(-1*(event.delta/120)), "units")

    def _load_engines(self):
        self.engines_list = backend.scan_available_engines()
        combo_values = [f"{e['name']}  ({e['redline']:,} RPM) — {e['rel_path']}" for e in self.engines_list]
        self.engine_combo["values"] = combo_values

        if self.engines_list:
            default_idx = 0
            for idx, e in enumerate(self.engines_list):
                if "sls_amg" in e["path"].lower():
                    default_idx = idx
                    break
            self.engine_combo.current(default_idx)
            self._select_engine_by_index(default_idx)

    def _select_engine_by_index(self, idx):
        if 0 <= idx < len(self.engines_list):
            engine_info = self.engines_list[idx]
            self._load_engine_file(engine_info["path"])

    def _load_engine_file(self, filepath):
        step_val = self._get_selected_step()
        specs = backend.parse_engine_specs(filepath, rpm_step=step_val)
        if not specs:
            messagebox.showerror("Error", f"Failed to parse engine file: {filepath}")
            return

        self.current_engine_specs = specs

        # Immediately update assets/main.mr to load this engine
        try:
            backend.configure_main_mr(filepath)
        except Exception:
            pass

        self.engine_name_lbl.config(text=specs["name"])
        idle_val = specs.get("idle_rpm", specs.get("starter_speed", 800))
        self.engine_stats_lbl.config(
            text=f"Redline: {specs['redline']:,} RPM  |  Idle / Dyno Min: {idle_val:,} RPM  |  File: {specs['file']}"
        )

        self._refresh_rpm_checkboxes()
        self._log(f"Loaded engine: {specs['name']} (Idle: {idle_val:,} RPM, Redline: {specs['redline']:,} RPM)")

    def _get_selected_step(self):
        sel = self.step_combo.get()
        if "500" in sel: return 500
        if "1,500" in sel: return 1500
        if "2,000" in sel: return 2000
        return 1000

    def _get_throttle_modes(self):
        sel = self.throttle_mode_combo.get()
        if "On-Throttle Only" in sel:
            return [("On", 1.0)]
        elif "Off-Throttle Only" in sel:
            return [("Off", 0.0)]
        else:
            return [("On", 1.0), ("Off", 0.0)]

    def _on_engine_selected(self, event):
        idx = self.engine_combo.current()
        self._select_engine_by_index(idx)

    def _on_browse_engine(self):
        filename = filedialog.askopenfilename(
            title="Select Engine (.mr) File",
            filetypes=[("Engine Definition Files", "*.mr"), ("All Files", "*.*")]
        )
        if filename:
            self._load_engine_file(filename)

    def _on_step_changed(self, event):
        if self.current_engine_specs:
            self._load_engine_file(self.current_engine_specs["path"])

    def _refresh_rpm_checkboxes(self):
        for widget in self.checkboxes_container.winfo_children():
            widget.destroy()

        self.rpm_vars.clear()

        if not self.current_engine_specs:
            return

        rpms = self.current_engine_specs["generated_rpms"]
        redline = self.current_engine_specs["redline"]

        cols = 5
        for idx, rpm in enumerate(rpms):
            var = tk.BooleanVar(value=True)
            self.rpm_vars[rpm] = var

            r = idx // cols
            c = idx % cols

            is_redline = (rpm == redline)
            label_text = f"{rpm:,} RPM" + (" (Redline)" if is_redline else "")
            
            cb_frame = tk.Frame(self.checkboxes_container, bg=self.panel_sub, padx=6, pady=4)
            cb_frame.grid(row=r, column=c, sticky="w", padx=6, pady=2)

            cb = tk.Checkbutton(cb_frame, text=label_text, variable=var,
                                font=("Segoe UI", 9, "bold" if is_redline else "normal"),
                                bg=self.panel_sub, 
                                fg="#fb7185" if is_redline else "#ffffff",
                                selectcolor=self.input_bg, 
                                activebackground=self.panel_sub,
                                activeforeground=self.accent_color,
                                command=self._update_selected_count)
            cb.pack(side=tk.LEFT)

        self._update_selected_count()

    def _get_blip_lift_rpms(self):
        if not self.current_engine_specs:
            return []
        sel = self.blip_lift_step_combo.get()
        if "Selected RPMs" in sel:
            return sorted([rpm for rpm, var in self.rpm_vars.items() if var.get()])
        if "Same as Stepped" in sel:
            return list(self.current_engine_specs.get("generated_rpms", []))

        step = 2000
        if "1,000" in sel: step = 1000
        elif "2,000" in sel: step = 2000
        elif "3,000" in sel: step = 3000

        idle_rpm = self.current_engine_specs.get("idle_rpm", self.current_engine_specs.get("starter_speed", 800))
        redline = self.current_engine_specs.get("redline", 7000)

        start_rpm = int(math.ceil((idle_rpm + 50) / step) * step)
        if start_rpm <= idle_rpm:
            start_rpm += step

        rpms = [r for r in range(start_rpm, redline, step)]
        if not rpms and redline > idle_rpm + 200:
            rpms = [(idle_rpm + redline) // 2]
        return rpms

    def _update_selected_count(self):
        selected_rpms = sum(1 for v in self.rpm_vars.values() if v.get())
        modes = self._get_throttle_modes()
        stepped_takes = selected_rpms * len(modes)

        special_takes = sum(1 for v in [self.startup_var.get(), self.idle_var.get(), self.max_rev_var.get(), self.shutdown_var.get()] if v)

        blip_lift_rpms = self._get_blip_lift_rpms()
        blip_takes = len(blip_lift_rpms) if self.blip_var.get() else 0
        lift_takes = len(blip_lift_rpms) if self.lift_var.get() else 0
        transient_takes = blip_takes + lift_takes

        total_takes = stepped_takes + special_takes + transient_takes

        # Update transient info label
        if (self.blip_var.get() or self.lift_var.get()) and blip_lift_rpms:
            rpm_sample = ", ".join(f"{r:,}" for r in blip_lift_rpms[:3])
            if len(blip_lift_rpms) > 3:
                rpm_sample += f", ... ({len(blip_lift_rpms)} stages)"
            self.blip_lift_info_lbl.config(text=f"[{rpm_sample}]")
        else:
            self.blip_lift_info_lbl.config(text="")

        parts = []
        if special_takes > 0:
            parts.append(f"{special_takes} Special")
        if transient_takes > 0:
            parts.append(f"{transient_takes} Transients ({blip_takes} Blip, {lift_takes} Lift)")
        if selected_rpms > 0:
            parts.append(f"{selected_rpms} RPMs ({stepped_takes} takes)")

        summary = " + ".join(parts) if parts else "0 takes"
        self.selected_count_lbl.config(text=f"{total_takes} Total Takes Selected ({summary})")

    def _select_all_rpms(self):
        for v in self.rpm_vars.values():
            v.set(True)
        self._update_selected_count()

    def _deselect_all_rpms(self):
        for v in self.rpm_vars.values():
            v.set(False)
        self._update_selected_count()

    def _on_browse_output_dir(self):
        d = filedialog.askdirectory(title="Select Output Directory", initialdir=self.out_dir_var.get())
        if d:
            self.out_dir_var.set(os.path.abspath(d))

    def _on_open_output_dir(self):
        d = self.out_dir_var.get()
        os.makedirs(d, exist_ok=True)
        os.startfile(d)

    def _log(self, msg):
        self.log_box.config(state=tk.NORMAL)
        t_str = time.strftime("[%H:%M:%S] ")
        self.log_box.insert(tk.END, t_str + msg + "\n")
        self.log_box.see(tk.END)
        self.log_box.config(state=tk.DISABLED)

    def _start_recording(self):
        if not self.current_engine_specs:
            messagebox.showwarning("No Engine", "Please select an engine .mr file first.")
            return

        selected_rpms = [rpm for rpm, var in self.rpm_vars.items() if var.get()]
        has_special = any([self.startup_var.get(), self.idle_var.get(), self.max_rev_var.get(), self.shutdown_var.get()])
        blip_lift_rpms = self._get_blip_lift_rpms()
        record_blips = self.blip_var.get()
        record_lifts = self.lift_var.get()
        transient_takes = (len(blip_lift_rpms) if record_blips else 0) + (len(blip_lift_rpms) if record_lifts else 0)

        if not selected_rpms and not has_special and transient_takes == 0:
            messagebox.showwarning("Nothing Selected", "Please select at least one RPM, special take, or blip/lift transient to record.")
            return

        try:
            duration = float(self.duration_var.get())
            if duration <= 0.5:
                raise ValueError()
        except ValueError:
            messagebox.showerror("Invalid Duration", "Please enter a valid duration in seconds (>= 0.5s).")
            return

        try:
            settle_delay = float(self.settle_delay_var.get())
            if settle_delay < 0.2:
                settle_delay = 0.2
        except ValueError:
            settle_delay = 1.5

        throttle_modes = self._get_throttle_modes()
        stepped_takes = len(selected_rpms) * len(throttle_modes)
        special_takes = sum(1 for v in [self.startup_var.get(), self.idle_var.get(), self.max_rev_var.get(), self.shutdown_var.get()] if v)
        total_takes = stepped_takes + special_takes + transient_takes

        out_dir = self.out_dir_var.get()
        os.makedirs(out_dir, exist_ok=True)

        # UI state during recording
        self.record_btn.config(state=tk.DISABLED)
        self.stop_btn.config(state=tk.NORMAL)
        self.engine_combo.config(state=tk.DISABLED)
        self.step_combo.config(state=tk.DISABLED)
        self.blip_lift_step_combo.config(state=tk.DISABLED)
        self.throttle_mode_combo.config(state=tk.DISABLED)
        self.progress_bar["value"] = 0
        self.progress_bar["maximum"] = total_takes

        self._log(f"Starting session: {total_takes} total takes ({special_takes} special, {transient_takes} transients, {stepped_takes} stepped RPMs).")

        self.runner = backend.AudioRecorderRunner(
            engine_path=self.current_engine_specs["path"],
            rpms_to_record=selected_rpms,
            duration=duration,
            settle_delay=settle_delay,
            throttle_modes=throttle_modes,
            make_seamless_loop=self.loop_var.get(),
            output_dir=out_dir,
            record_startup=self.startup_var.get(),
            record_idle=self.idle_var.get(),
            record_max_rev=self.max_rev_var.get(),
            record_shutdown=self.shutdown_var.get(),
            record_blips=record_blips,
            record_lifts=record_lifts,
            blip_lift_rpms=blip_lift_rpms,
            progress_cb=self._on_progress_update,
            log_cb=self._on_runner_log,
            finished_cb=self._on_runner_finished
        )
        self.runner.start()

    def _stop_recording(self):
        if self.runner:
            self.runner.cancel()
            self._log("Stopping recording session...")
            self.stop_btn.config(state=tk.DISABLED)

    def _on_progress_update(self, take_idx, total_takes, target_rpm, mode_suffix, current_rpm, status_text):
        def _update():
            self.progress_bar["value"] = max(0, take_idx - 1)
            rpm_display = f"{target_rpm} RPM" if target_rpm > 0 else ""
            self.status_lbl.config(
                text=f"Take {take_idx}/{total_takes} ({mode_suffix} {rpm_display}) | Live: {current_rpm:.0f} RPM | {status_text}"
            )
        self.root.after(0, _update)

    def _on_runner_log(self, message):
        self.root.after(0, lambda: self._log(message))

    def _on_runner_finished(self, success, files, message):
        def _finished():
            self.record_btn.config(state=tk.NORMAL)
            self.stop_btn.config(state=tk.DISABLED)
            self.engine_combo.config(state="readonly")
            self.step_combo.config(state="readonly")
            self.blip_lift_step_combo.config(state="readonly")
            self.throttle_mode_combo.config(state="readonly")
            self.progress_bar["value"] = self.progress_bar["maximum"]

            if success:
                self.status_lbl.config(text=f"Completed! {len(files)} takes saved.")
                self._log(f"Completed! {len(files)} audio takes saved in {self.out_dir_var.get()}")
                
                res = messagebox.askyesno(
                    "Recording Complete",
                    f"Successfully recorded {len(files)} audio takes!\n\nIncludes special takes, blips/lifts & seamless loops.\n\nOpen output folder now?"
                )
                if res:
                    self._on_open_output_dir()
            else:
                self.status_lbl.config(text=f"Stopped: {message}")
                self._log(f"Recording ended: {message}")

        self.root.after(0, _finished)

    def _on_close(self):
        if self.runner and self.runner.thread and self.runner.thread.is_alive():
            if messagebox.askyesno("Quit", "A recording session is currently active. Do you want to cancel and exit?"):
                self.runner.cancel()
                self.root.destroy()
        else:
            self.root.destroy()

def main():
    root = tk.Tk()
    app = EngineRecorderApp(root)
    root.mainloop()

if __name__ == "__main__":
    main()
