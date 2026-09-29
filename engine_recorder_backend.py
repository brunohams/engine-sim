import os
import re
import glob
import time
import subprocess
import threading
import wave
import numpy as np
import ctypes
from ctypes import wintypes

# Define the shared memory structure matching C++ SimBridgeData
class SimBridgeData(ctypes.Structure):
    _pack_ = 8
    _fields_ = [
        ("magic", wintypes.DWORD),
        ("command", ctypes.c_int32),
        ("targetRpm", ctypes.c_int32),
        ("throttle", ctypes.c_double),
        ("status", ctypes.c_int32),
        ("currentRpm", ctypes.c_double),
        ("frameCount", ctypes.c_int32),
        ("stableFrames", ctypes.c_int32),
    ]

# Win32 API Definitions for DLL Injection and Memory Mapping
kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

PROCESS_ALL_ACCESS = 0x1F0FFF
MEM_COMMIT = 0x1000
MEM_RESERVE = 0x2000
PAGE_READWRITE = 0x04
FILE_MAP_ALL_ACCESS = 0xF001F

kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE
kernel32.VirtualAllocEx.argtypes = [wintypes.HANDLE, wintypes.LPVOID, ctypes.c_size_t, wintypes.DWORD, wintypes.DWORD]
kernel32.VirtualAllocEx.restype = wintypes.LPVOID
kernel32.WriteProcessMemory.argtypes = [wintypes.HANDLE, wintypes.LPVOID, wintypes.LPCVOID, ctypes.c_size_t, ctypes.POINTER(ctypes.c_size_t)]
kernel32.WriteProcessMemory.restype = wintypes.BOOL
kernel32.CreateRemoteThread.argtypes = [wintypes.HANDLE, wintypes.LPVOID, ctypes.c_size_t, wintypes.LPVOID, wintypes.LPVOID, wintypes.DWORD, wintypes.LPDWORD]
kernel32.CreateRemoteThread.restype = wintypes.HANDLE
kernel32.GetProcAddress.argtypes = [wintypes.HMODULE, wintypes.LPCSTR]
kernel32.GetProcAddress.restype = wintypes.LPVOID
kernel32.GetModuleHandleA.argtypes = [wintypes.LPCSTR]
kernel32.GetModuleHandleA.restype = wintypes.HMODULE
kernel32.OpenFileMappingA.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCSTR]
kernel32.OpenFileMappingA.restype = wintypes.HANDLE
kernel32.MapViewOfFile.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, ctypes.c_size_t]
kernel32.MapViewOfFile.restype = wintypes.LPVOID
kernel32.UnmapViewOfFile.argtypes = [wintypes.LPCVOID]
kernel32.UnmapViewOfFile.restype = wintypes.BOOL
kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL

def inject_dll(pid, dll_path):
    """Injects a 64-bit DLL into the target process via CreateRemoteThread."""
    h_proc = kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
    if not h_proc:
        raise RuntimeError(f"OpenProcess failed: {ctypes.get_last_error()}")
    
    try:
        dll_bytes = os.path.abspath(dll_path).encode('utf-8') + b'\x00'
        remote_mem = kernel32.VirtualAllocEx(h_proc, None, len(dll_bytes), MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE)
        if not remote_mem:
            raise RuntimeError(f"VirtualAllocEx failed: {ctypes.get_last_error()}")
            
        written = ctypes.c_size_t(0)
        if not kernel32.WriteProcessMemory(h_proc, remote_mem, dll_bytes, len(dll_bytes), ctypes.byref(written)):
            raise RuntimeError(f"WriteProcessMemory failed: {ctypes.get_last_error()}")
            
        h_k32 = kernel32.GetModuleHandleA(b"kernel32.dll")
        load_lib = kernel32.GetProcAddress(h_k32, b"LoadLibraryA")
        
        h_thread = kernel32.CreateRemoteThread(h_proc, None, 0, load_lib, remote_mem, 0, None)
        if not h_thread:
            raise RuntimeError(f"CreateRemoteThread failed: {ctypes.get_last_error()}")
            
        kernel32.WaitForSingleObject(h_thread, 5000)
        kernel32.CloseHandle(h_thread)
    finally:
        kernel32.CloseHandle(h_proc)

import math
import shutil

def configure_main_mr(engine_path):
    """
    Configures assets/main.mr to import the target engine file.
    If the engine file is outside assets/, copies it to assets/engines/custom/.
    """
    assets_dir = os.path.abspath("assets")
    target_engine_abs = os.path.abspath(engine_path)

    try:
        common = os.path.commonpath([assets_dir, target_engine_abs])
    except ValueError:
        common = ""

    if common == assets_dir:
        rel_engine_path = os.path.relpath(target_engine_abs, assets_dir).replace("\\", "/")
    else:
        custom_dir = os.path.join(assets_dir, "engines", "custom")
        os.makedirs(custom_dir, exist_ok=True)
        dest_file = os.path.join(custom_dir, os.path.basename(target_engine_abs))
        shutil.copy2(target_engine_abs, dest_file)
        rel_engine_path = os.path.relpath(dest_file, assets_dir).replace("\\", "/")

    main_mr_path = os.path.join(assets_dir, "main.mr")
    main_mr_content = (
        'import "engine_sim.mr"\n'
        'import "themes/default.mr"\n'
        f'import "{rel_engine_path}"\n'
        'use_default_theme()\n'
        'main()\n'
    )
    with open(main_mr_path, "w", encoding="utf-8") as f:
        f.write(main_mr_content)
    return rel_engine_path

def parse_engine_specs(filepath, rpm_step=1000):
    """
    Parses a .mr file to extract engine name, redline, starter/idle speed,
    dyno minimum speed, and generates the stepped RPM list strictly above idle.
    """
    if not os.path.exists(filepath):
        return None

    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    base_name = os.path.splitext(os.path.basename(filepath))[0]
    info = {
        "file": os.path.basename(filepath),
        "path": os.path.abspath(filepath),
        "name": base_name.replace("_", " ").title(),
        "redline": 7000,
        "starter_speed": 800,
        "dyno_min_speed": None,
        "idle_rpm": 800,
        "rev_limit": None,
        "timing_samples": [],
        "generated_rpms": []
    }

    # Extract engine name string
    m_name = re.search(r'name\s*:\s*["\']([^"\']+)["\']', content)
    if m_name:
        info["name"] = m_name.group(1).strip()

    # Redline
    m_redline = re.search(r'redline\s*:\s*(\d+)\s*\*\s*units\.rpm', content)
    if m_redline:
        info["redline"] = int(m_redline.group(1))

    # Starter speed
    m_starter = re.search(r'starter_speed\s*:\s*(\d+)\s*\*\s*units\.rpm', content)
    if m_starter:
        info["starter_speed"] = int(m_starter.group(1))

    # Dyno minimum speed
    m_dyno_min = re.search(r'dyno_min_speed\s*:\s*(\d+)\s*\*\s*units\.rpm', content)
    if m_dyno_min:
        info["dyno_min_speed"] = int(m_dyno_min.group(1))

    # Calculate effective idle RPM
    starter = info.get("starter_speed") or 800
    dyno_min = info.get("dyno_min_speed") or 0
    idle_rpm = max(starter, dyno_min)
    info["idle_rpm"] = idle_rpm

    # Rev limit
    m_rev = re.search(r'rev_limit\s*:\s*(\d+)\s*\*\s*units\.rpm', content)
    if m_rev:
        info["rev_limit"] = int(m_rev.group(1))

    # Timing samples
    samples = re.findall(r'add_sample\s*\(\s*(\d+)\s*\*\s*units\.rpm', content)
    if samples:
        info["timing_samples"] = sorted(list(set([int(s) for s in samples if int(s) > 0])))

    # Generate stepped RPMs strictly ABOVE idle RPM
    max_rpm = info["redline"]
    step = max(100, int(rpm_step))
    start_rpm = int(math.ceil((idle_rpm + 50) / step) * step)
    if start_rpm <= idle_rpm:
        start_rpm += step

    rpms = list(range(start_rpm, max_rpm + 1, step))
    if not rpms or rpms[0] > max_rpm:
        rpms = [max_rpm]
    elif rpms[-1] < max_rpm and (max_rpm - rpms[-1]) >= (step // 2):
        rpms.append(max_rpm)

    info["generated_rpms"] = rpms
    return info

def scan_available_engines(base_dir=None):
    """Scans assets/engines recursively for all .mr files."""
    if base_dir is None:
        base_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "assets", "engines"))
    
    if not os.path.exists(base_dir):
        return []

    mr_files = glob.glob(os.path.join(base_dir, "**", "*.mr"), recursive=True)
    engines = []
    for f in mr_files:
        rel = os.path.relpath(f, base_dir)
        try:
            specs = parse_engine_specs(f)
            if specs:
                engines.append({
                    "path": f,
                    "rel_path": rel,
                    "name": specs["name"],
                    "redline": specs["redline"],
                    "specs": specs
                })
        except Exception:
            pass

    engines.sort(key=lambda x: x["name"])
    return engines

def trim_silence(wav_path, out_path=None, threshold_db=-40.0, margin_sec=0.05, window_ms=10):
    """
    Trims leading and trailing silence from a WAV file.
    - threshold_db: RMS level (in dB relative to int16 max) below which audio is considered silence.
    - margin_sec:   Extra audio margin to keep before/after detected sound for natural feel.
    - window_ms:    Sliding window size in ms for RMS computation.
    Returns the trimmed duration in seconds, or None on failure.
    """
    if out_path is None:
        out_path = wav_path  # overwrite in-place

    with wave.open(wav_path, 'rb') as w:
        rate = w.getframerate()
        nchannels = w.getnchannels()
        sampwidth = w.getsampwidth()
        nframes = w.getnframes()
        frames = w.readframes(nframes)

    if nframes == 0:
        return None

    data = np.frombuffer(frames, dtype=np.int16).reshape(-1, nchannels).astype(np.float64)

    # Mix to mono for silence detection
    mono = data.mean(axis=1)

    # RMS threshold in linear amplitude (relative to int16 max 32767)
    threshold_linear = 32767.0 * (10.0 ** (threshold_db / 20.0))

    # Sliding window RMS
    win_samples = max(1, int(window_ms * rate / 1000))
    num_windows = len(mono) // win_samples
    if num_windows == 0:
        return None

    truncated = mono[:num_windows * win_samples].reshape(num_windows, win_samples)
    rms_per_window = np.sqrt(np.mean(truncated ** 2, axis=1))

    # Find first and last window above threshold
    above = np.where(rms_per_window > threshold_linear)[0]
    if len(above) == 0:
        return None  # entirely silent

    first_window = above[0]
    last_window = above[-1]

    # Convert back to sample indices with margin
    margin_samples = int(margin_sec * rate)
    start_sample = max(0, first_window * win_samples - margin_samples)
    end_sample = min(len(data), (last_window + 1) * win_samples + margin_samples)

    trimmed = data[start_sample:end_sample]
    out_int16 = np.clip(trimmed, -32768, 32767).astype(np.int16)

    with wave.open(out_path, 'wb') as w:
        w.setnchannels(nchannels)
        w.setsampwidth(sampwidth)
        w.setframerate(rate)
        w.writeframes(out_int16.tobytes())

    return len(out_int16) / rate


def create_perfect_loop(raw_wav_path, out_wav_path, rpm, target_duration=3.0, xfade_sec=0.25, lead_trim_sec=0.4):
    """
    Transforms raw recorded audio into a mathematically seamless audio loop.
    1. Trims leading buffer to avoid any previous RPM leakage or onset transient.
    2. Aligns loop duration to an exact integer number of 4-stroke combustion cycles.
    3. Finds the phase-optimal cut point using normalized cross-correlation.
    4. Applies an equal-power sine/cosine crossfade between tail and head.
    The resulting audio loops indefinitely with 0 clicks, 0 pops, and seamless continuity.
    """
    with wave.open(raw_wav_path, 'rb') as w:
        rate = w.getframerate()
        nchannels = w.getnchannels()
        sampwidth = w.getsampwidth()
        nframes = w.getnframes()
        frames = w.readframes(nframes)

    data = np.frombuffer(frames, dtype=np.int16).reshape(-1, nchannels).astype(np.float64)

    # 1. Trim leading buffer to avoid any previous RPM leakage or onset transient
    lead_samples = int(lead_trim_sec * rate)
    if len(data) > lead_samples + int(target_duration * rate):
        data = data[lead_samples:]

    # 2. Cycle-aligned loop duration (4-stroke engine cycle = 120 / RPM seconds)
    safe_rpm = max(400, rpm)
    cycle_period_sec = 120.0 / safe_rpm
    cycle_samples = cycle_period_sec * rate

    num_cycles = max(1, int(round(target_duration / cycle_period_sec)))
    loop_samples = int(round(num_cycles * cycle_samples))
    xfade_samples = int(xfade_sec * rate)

    # 3. Search in small window (+/- 0.5 cycle) for best phase alignment
    search_range = int(cycle_samples * 0.5)
    best_offset = 0
    best_corr = -1e12

    if loop_samples + xfade_samples + search_range <= len(data):
        ref = data[:xfade_samples, 0]
        ref_norm = np.linalg.norm(ref) + 1e-9
        for off in range(-search_range, search_range, 2):
            idx = loop_samples + off
            cand = data[idx : idx + xfade_samples, 0]
            corr = np.dot(ref, cand) / (ref_norm * (np.linalg.norm(cand) + 1e-9))
            if corr > best_corr:
                best_corr = corr
                best_offset = off
        loop_samples += best_offset

    # Ensure valid bounds
    if len(data) < loop_samples + xfade_samples:
        loop_samples = len(data) - xfade_samples

    source = data[:loop_samples + xfade_samples]
    head = source[:xfade_samples]
    tail = source[loop_samples : loop_samples + xfade_samples]

    # 4. Equal-power crossfade curve
    theta = np.linspace(0, np.pi / 2, xfade_samples)[:, np.newaxis]
    alpha = np.sin(theta)  # 0.0 -> 1.0 (fade-in head)
    beta = np.cos(theta)   # 1.0 -> 0.0 (fade-out tail)

    blended = head * alpha + tail * beta

    result = np.empty((loop_samples, nchannels), dtype=np.float64)
    result[:xfade_samples] = blended
    result[xfade_samples:] = source[xfade_samples:loop_samples]

    out_int16 = np.clip(result, -32768, 32767).astype(np.int16)

    with wave.open(out_wav_path, 'wb') as w:
        w.setnchannels(nchannels)
        w.setsampwidth(sampwidth)
        w.setframerate(rate)
        w.writeframes(out_int16.tobytes())

    return len(out_int16) / rate

class AudioRecorderRunner:
    """
    Manages automated recording of engine audio:
    - Stepped RPM takes (On-Throttle 1.0 & Off-Throttle 0.0) with seamless loops
    - Natural Idle take (seamless loop)
    - Maximum RPM Revving take (full throttle at redline, seamless loop)
    - Engine Turning On take (cold start / cranking to idle, one-shot)
    - Engine Turning Off take (ignition cut spin-down to stop, one-shot)
    """
    def __init__(self, engine_path, rpms_to_record=None, duration=3.0, settle_delay=1.5,
                 throttle_modes=None, make_seamless_loop=True, output_dir="recordings",
                 record_startup=False, record_idle=False, record_max_rev=False, record_shutdown=False,
                 progress_cb=None, log_cb=None, finished_cb=None):
        self.engine_path = os.path.abspath(engine_path)
        self.rpms_to_record = sorted(list(rpms_to_record)) if rpms_to_record else []
        self.duration = float(duration)
        self.settle_delay = max(0.5, float(settle_delay))
        self.make_seamless_loop = bool(make_seamless_loop)
        self.output_dir = os.path.abspath(output_dir)

        self.record_startup = bool(record_startup)
        self.record_idle = bool(record_idle)
        self.record_max_rev = bool(record_max_rev)
        self.record_shutdown = bool(record_shutdown)

        # Default throttle modes: Both ("On" = 1.0, "Off" = 0.0)
        if throttle_modes is None:
            self.throttle_modes = [("On", 1.0), ("Off", 0.0)]
        else:
            self.throttle_modes = throttle_modes

        self.progress_cb = progress_cb
        self.log_cb = log_cb
        self.finished_cb = finished_cb
        
        self.is_cancelled = False
        self.thread = None
        self.proc = None
        self.h_map = None
        self.p_bridge = None
        self.bridge = None

    def start(self):
        self.is_cancelled = False
        self.thread = threading.Thread(target=self._run, daemon=True)
        self.thread.start()

    def cancel(self):
        self.is_cancelled = True
        self._log("Cancellation requested by user...")
        if self.proc:
            try:
                self.proc.terminate()
            except Exception:
                pass

    def _log(self, msg):
        if self.log_cb:
            self.log_cb(msg)
        else:
            print(f"[Recorder] {msg}")

    def _record_audio_take(self, recorder_exe, out_filepath, target_rpm, label_suffix, is_loop=True,
                           take_idx=1, total_tasks=1):
        """Helper to record audio and optionally generate a seamless loop."""
        out_filename = os.path.basename(out_filepath)
        if is_loop and self.make_seamless_loop:
            raw_temp_filepath = os.path.join(self.output_dir, f"temp_raw_{label_suffix}.wav")
            rec_dur = self.duration + 1.2

            self._log(f"Recording {rec_dur:.1f}s raw take for seamless loop processing...")
            if self.progress_cb:
                self.progress_cb(take_idx, total_tasks, target_rpm, label_suffix,
                                 self.bridge.currentRpm, f"Recording audio ({self.duration:.1f}s)...")

            subprocess.run([
                recorder_exe,
                str(self.proc.pid),
                raw_temp_filepath,
                str(rec_dur)
            ], capture_output=True, text=True)

            if os.path.exists(raw_temp_filepath) and os.path.getsize(raw_temp_filepath) > 1000:
                self._log(f"Processing perfect seamless loop -> {out_filename}")
                loop_dur = create_perfect_loop(raw_temp_filepath, out_filepath, target_rpm,
                                               target_duration=self.duration)
                try:
                    os.remove(raw_temp_filepath)
                except Exception:
                    pass

                size_kb = os.path.getsize(out_filepath) // 1024
                self._log(f"Saved seamless loop: {out_filename} ({size_kb} KB, {loop_dur:.2f}s)")
                return True
            else:
                self._log(f"Error capturing take {take_idx}.")
                return False
        else:
            self._log(f"Recording direct audio take -> {out_filename}")
            if self.progress_cb:
                self.progress_cb(take_idx, total_tasks, target_rpm, label_suffix,
                                 self.bridge.currentRpm, f"Recording audio ({self.duration:.1f}s)...")

            subprocess.run([
                recorder_exe,
                str(self.proc.pid),
                out_filepath,
                str(self.duration)
            ], capture_output=True, text=True)

            if os.path.exists(out_filepath) and os.path.getsize(out_filepath) > 1000:
                size_kb = os.path.getsize(out_filepath) // 1024
                self._log(f"Saved: {out_filename} ({size_kb} KB)")
                return True
            else:
                self._log(f"Error capturing take {take_idx}.")
                return False

    def _hold_and_settle(self, target_rpm, throttle_val, mode_label, take_idx, total_tasks):
        """Holds engine at target RPM & throttle until stable, followed by acoustic settle delay."""
        self.bridge.status = 0
        self.bridge.stableFrames = 0
        self.bridge.command = 1
        self.bridge.targetRpm = target_rpm
        self.bridge.throttle = throttle_val

        t0 = time.time()
        timeout = 10.0
        while (time.time() - t0) < timeout:
            if self.is_cancelled:
                return False

            current_rpm = self.bridge.currentRpm
            status_code = self.bridge.status
            status_msg = "Starting..." if status_code == 1 else \
                         f"Stabilizing to {target_rpm} RPM..." if status_code == 2 else \
                         "RPM Stable" if status_code == 3 else "Initializing..."

            if self.progress_cb:
                self.progress_cb(take_idx, total_tasks, target_rpm, mode_label, current_rpm, status_msg)

            if status_code == 3:
                break
            time.sleep(0.08)

        if self.is_cancelled:
            return False

        # Acoustic settle delay
        self._log(f"RPM locked at {self.bridge.currentRpm:.0f}. Waiting {self.settle_delay:.1f}s settle delay...")
        t_settle_start = time.time()
        while time.time() - t_settle_start < self.settle_delay:
            if self.is_cancelled: return False
            if self.progress_cb:
                rem = self.settle_delay - (time.time() - t_settle_start)
                self.progress_cb(take_idx, total_tasks, target_rpm, mode_label,
                                 self.bridge.currentRpm, f"Acoustic settle delay ({rem:.1f}s)...")
            time.sleep(0.08)

        return not self.is_cancelled

    def _run(self):
        recorded_files = []
        app_exe = os.path.abspath("bin/engine-sim-app.exe")
        recorder_exe = os.path.abspath("bin/process_recorder.exe")
        hook_dll = os.path.abspath("bin/engine_hook.dll")
        session_tmp = os.path.abspath("bin/session_info.tmp")

        if not os.path.exists(app_exe):
            self._log(f"Error: Could not find {app_exe}")
            if self.finished_cb: self.finished_cb(False, [], "Simulator executable not found")
            return

        if not os.path.exists(hook_dll):
            self._log(f"Error: Could not find {hook_dll}")
            if self.finished_cb: self.finished_cb(False, [], "Hook DLL not found")
            return

        if not os.path.exists(recorder_exe):
            self._log(f"Error: Could not find {recorder_exe}")
            if self.finished_cb: self.finished_cb(False, [], "Process recorder executable not found")
            return

        os.makedirs(self.output_dir, exist_ok=True)

        engine_basename = os.path.splitext(os.path.basename(self.engine_path))[0]
        specs = parse_engine_specs(self.engine_path)
        idle_rpm = specs["idle_rpm"] if specs else 800
        redline = specs["redline"] if specs else 7000
        max_rev_rpm = max(redline - 100, int(redline * 0.98))

        # Calculate task counts
        total_tasks = 0
        if self.record_startup: total_tasks += 1
        if self.record_idle: total_tasks += 1
        total_tasks += len(self.rpms_to_record) * len(self.throttle_modes)
        if self.record_max_rev: total_tasks += 1
        if self.record_shutdown: total_tasks += 1

        self._log(f"Starting session for engine: {engine_basename}")
        self._log(f"Special Takes -> Startup: {self.record_startup}, Idle: {self.record_idle}, MaxRev: {self.record_max_rev}, Shutdown: {self.record_shutdown}")
        self._log(f"Stepped RPMs ({len(self.rpms_to_record)}): {self.rpms_to_record}")
        self._log(f"Total takes to record: {total_tasks}")

        current_task_idx = 0

        try:
            # 1. Update assets/main.mr to load the chosen engine
            rel_engine = configure_main_mr(self.engine_path)
            self._log(f"Configured assets/main.mr -> import \"{rel_engine}\"")

            with open(session_tmp, "w", encoding="utf-8") as f:
                f.write(self.engine_path)

            # 2. Launch engine simulator process
            self._log("Launching engine-sim-app.exe...")

            if self.record_startup:
                # Record engine turning on (Startup) right as simulator boots!
                current_task_idx += 1
                startup_filename = f"{engine_basename}_Startup.wav"
                startup_filepath = os.path.join(self.output_dir, startup_filename)
                self._log(f"\n--- [Take {current_task_idx}/{total_tasks}] Engine Startup (Cold Start Cranking & Fire-up) ---")

                self.proc = subprocess.Popen([app_exe], cwd="bin")
                self._log(f"Simulator started (PID: {self.proc.pid})")

                # Immediately start recorder to catch cranking sound
                rec_dur = 3.8
                rec_proc = subprocess.Popen([recorder_exe, str(self.proc.pid), startup_filepath, str(rec_dur)])

                if self.progress_cb:
                    self.progress_cb(current_task_idx, total_tasks, 0, "Startup", 0, "Recording Engine Startup (cranking & ignition)...")

                time.sleep(0.05)
                inject_dll(self.proc.pid, hook_dll)
                self._log("Control bridge DLL injected.")

                rec_proc.wait(timeout=10)
                if os.path.exists(startup_filepath) and os.path.getsize(startup_filepath) > 1000:
                    # Trim leading/trailing silence from startup recording
                    trimmed_dur = trim_silence(startup_filepath)
                    if trimmed_dur:
                        size_kb = os.path.getsize(startup_filepath) // 1024
                        self._log(f"Saved: {startup_filename} ({size_kb} KB, {trimmed_dur:.1f}s after silence trim, one-shot)")
                    else:
                        size_kb = os.path.getsize(startup_filepath) // 1024
                        self._log(f"Saved: {startup_filename} ({size_kb} KB, one-shot)")
                    recorded_files.append(startup_filepath)
            else:
                self.proc = subprocess.Popen([app_exe], cwd="bin")
                self._log(f"Simulator started (PID: {self.proc.pid})")
                time.sleep(1.0)
                if self.is_cancelled: return
                self._log("Injecting control bridge DLL...")
                inject_dll(self.proc.pid, hook_dll)
                self._log("Control bridge DLL injected.")

            time.sleep(0.5)

            # 3. Connect to named shared memory bridge
            retries = 0
            while not self.h_map and retries < 25:
                if self.is_cancelled: return
                time.sleep(0.1)
                self.h_map = kernel32.OpenFileMappingA(FILE_MAP_ALL_ACCESS, False, b"Local\\EngineSimBridge")
                retries += 1

            if not self.h_map:
                raise RuntimeError("Failed to open EngineSimBridge shared memory mapping.")

            self.p_bridge = kernel32.MapViewOfFile(self.h_map, FILE_MAP_ALL_ACCESS, 0, 0, ctypes.sizeof(SimBridgeData))
            self.bridge = SimBridgeData.from_address(self.p_bridge)
            self._log(f"Connected to control bridge (Magic: 0x{self.bridge.magic:X})")

            # 4. Record Idle Take (Seamless Loop)
            if self.record_idle and not self.is_cancelled:
                current_task_idx += 1
                self._log(f"\n--- [Take {current_task_idx}/{total_tasks}] Engine Idle ({idle_rpm} RPM - Seamless Loop) ---")
                if self._hold_and_settle(idle_rpm, 0.0, "Idle", current_task_idx, total_tasks):
                    out_filename = f"{engine_basename}_Idle.wav"
                    final_filepath = os.path.join(self.output_dir, out_filename)
                    if self._record_audio_take(recorder_exe, final_filepath, idle_rpm, "Idle",
                                               is_loop=True, take_idx=current_task_idx, total_tasks=total_tasks):
                        recorded_files.append(final_filepath)
                time.sleep(0.15)

            # 5. Record Stepped RPM Takes
            for target_rpm in self.rpms_to_record:
                for mode_suffix, thr_value in self.throttle_modes:
                    if self.is_cancelled: break

                    current_task_idx += 1
                    mode_desc = f"Throttle {mode_suffix} ({int(thr_value*100)}%)"
                    self._log(f"\n--- [Take {current_task_idx}/{total_tasks}] {target_rpm} RPM - {mode_desc} ---")

                    if self._hold_and_settle(target_rpm, thr_value, mode_suffix, current_task_idx, total_tasks):
                        out_filename = f"{engine_basename}_{target_rpm}rpm_{mode_suffix}.wav"
                        final_filepath = os.path.join(self.output_dir, out_filename)
                        if self._record_audio_take(recorder_exe, final_filepath, target_rpm, mode_suffix,
                                                   is_loop=True, take_idx=current_task_idx, total_tasks=total_tasks):
                            recorded_files.append(final_filepath)
                    time.sleep(0.15)

            # 6. Record Maximum RPM Revving Take (Seamless Loop)
            if self.record_max_rev and not self.is_cancelled:
                current_task_idx += 1
                self._log(f"\n--- [Take {current_task_idx}/{total_tasks}] Maximum RPM Revving ({max_rev_rpm} RPM - Full Throttle) ---")
                if self._hold_and_settle(max_rev_rpm, 1.0, "MaxRev", current_task_idx, total_tasks):
                    out_filename = f"{engine_basename}_MaxRev.wav"
                    final_filepath = os.path.join(self.output_dir, out_filename)
                    if self._record_audio_take(recorder_exe, final_filepath, max_rev_rpm, "MaxRev",
                                               is_loop=True, take_idx=current_task_idx, total_tasks=total_tasks):
                        recorded_files.append(final_filepath)
                time.sleep(0.15)

            # 7. Record Engine Turning Off (Shutdown - One-Shot)
            if self.record_shutdown and not self.is_cancelled:
                current_task_idx += 1
                self._log(f"\n--- [Take {current_task_idx}/{total_tasks}] Engine Shutdown (Turn Off / Spin-Down) ---")
                
                # Bring engine to idle first
                self.bridge.targetRpm = idle_rpm
                self.bridge.throttle = 0.0
                time.sleep(1.0)

                shutdown_filename = f"{engine_basename}_Shutdown.wav"
                shutdown_filepath = os.path.join(self.output_dir, shutdown_filename)

                if self.progress_cb:
                    self.progress_cb(current_task_idx, total_tasks, 0, "Shutdown", self.bridge.currentRpm, "Recording Engine Shutdown (ignition cut)...")

                rec_dur = 3.5
                rec_proc = subprocess.Popen([recorder_exe, str(self.proc.pid), shutdown_filepath, str(rec_dur)])
                time.sleep(0.6) # Record 0.6s running idle snippet

                self._log("Cutting ignition for shutdown...")
                self.bridge.command = 4 # Cut ignition
                rec_proc.wait(timeout=10)

                if os.path.exists(shutdown_filepath) and os.path.getsize(shutdown_filepath) > 1000:
                    # Trim leading/trailing silence from shutdown recording
                    trimmed_dur = trim_silence(shutdown_filepath)
                    if trimmed_dur:
                        size_kb = os.path.getsize(shutdown_filepath) // 1024
                        self._log(f"Saved: {shutdown_filename} ({size_kb} KB, {trimmed_dur:.1f}s after silence trim, one-shot)")
                    else:
                        size_kb = os.path.getsize(shutdown_filepath) // 1024
                        self._log(f"Saved: {shutdown_filename} ({size_kb} KB, one-shot)")
                    recorded_files.append(shutdown_filepath)

            self._log(f"\nAll requested audio takes processed successfully! ({len(recorded_files)} files saved)")
            if self.finished_cb:
                self.finished_cb(True, recorded_files, f"Successfully recorded {len(recorded_files)} audio takes!")

        except Exception as ex:
            self._log(f"Error during recording session: {str(ex)}")
            if self.finished_cb:
                self.finished_cb(False, recorded_files, str(ex))

        finally:
            self._cleanup()

    def _cleanup(self):
        if self.proc:
            try:
                self._log("Stopping engine simulation process...")
                self.proc.terminate()
                self.proc.wait(timeout=2.0)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass
            self.proc = None

        if self.p_bridge:
            try:
                kernel32.UnmapViewOfFile(self.p_bridge)
            except Exception:
                pass
            self.p_bridge = None

        if self.h_map:
            try:
                kernel32.CloseHandle(self.h_map)
            except Exception:
                pass
            self.h_map = None
