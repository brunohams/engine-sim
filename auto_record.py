"""
Engine Simulator - Automated Audio Recorder & Controller
--------------------------------------------------------
Allows passing instructions like:
    "record the engine file X on RPM 4000 for 3 seconds"
to automatically load the engine, hold the exact target RPM via dyno,
and record lossless WAV audio.
"""

import os
import sys
import re
import time
import json
import glob
import ctypes
import argparse
import threading
import subprocess
from dataclasses import dataclass
from typing import Optional, List, Dict, Any

import soundfile as sf
import pygetwindow as gw

try:
    import pydirectinput
    pydirectinput.PAUSE = 0.05
    pydirectinput.FAILSAFE = False
    HAS_DIRECTINPUT = True
except ImportError:
    HAS_DIRECTINPUT = False

try:
    import soundcard as sc
    HAS_SOUNDCARD = True
except ImportError:
    HAS_SOUNDCARD = False


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
BIN_DIR = os.path.join(BASE_DIR, "bin")
RECORDINGS_DIR = os.path.join(BASE_DIR, "recordings")
SIM_EXE_PATH = os.path.join(BIN_DIR, "engine-sim-app.exe")
NATIVE_RECORDER_PATH = os.path.join(BIN_DIR, "process_recorder.exe")
SESSION_INFO_PATH = os.path.join(BIN_DIR, "session_info.tmp")

os.makedirs(RECORDINGS_DIR, exist_ok=True)


@dataclass
class RecordInstruction:
    raw_instruction: str
    engine_query: str
    resolved_engine_path: str
    target_rpm: int
    duration_seconds: float
    output_filename: Optional[str] = None
    throttle_key: str = "r"


def get_loopback_recorder():
    """Finds the loopback audio device for the system's active speakers."""
    if not HAS_SOUNDCARD:
        return None
    loopbacks = [m for m in sc.all_microphones(include_loopback=True) if m.isloopback]
    if not loopbacks:
        return None
    speaker = sc.default_speaker()
    matched = [m for m in loopbacks if speaker.name in m.name]
    return matched[0] if matched else loopbacks[0]


def resolve_engine_file(query: str, base_dir: str = BASE_DIR) -> Optional[str]:
    """
    Intelligently resolves an engine query into a full absolute file path.
    Searches exact path, relative to assets/engines, recursive in assets/,
    and user Downloads folder.
    """
    clean_query = query.strip("\"' \t\r\n")

    # 1. Exact absolute or relative path
    if os.path.isabs(clean_query) and os.path.exists(clean_query):
        return os.path.abspath(clean_query)

    direct_rel = os.path.join(base_dir, clean_query)
    if os.path.exists(direct_rel):
        return os.path.abspath(direct_rel)

    if not clean_query.lower().endswith(".mr"):
        if os.path.exists(direct_rel + ".mr"):
            return os.path.abspath(direct_rel + ".mr")

    # 2. Check directly under assets/engines/
    engines_dir = os.path.join(base_dir, "assets", "engines")
    eng_rel = os.path.join(engines_dir, clean_query)
    if os.path.exists(eng_rel):
        return os.path.abspath(eng_rel)
    if not clean_query.lower().endswith(".mr") and os.path.exists(eng_rel + ".mr"):
        return os.path.abspath(eng_rel + ".mr")

    # 3. Recursive search in assets/
    assets_dir = os.path.join(base_dir, "assets")
    filename_to_match = os.path.basename(clean_query)
    if not filename_to_match.lower().endswith(".mr"):
        filename_to_match += ".mr"

    matches = []
    for root, _, files in os.walk(assets_dir):
        for f in files:
            if f.lower() == filename_to_match.lower():
                matches.append(os.path.join(root, f))
            elif clean_query.lower() in f.lower() and f.lower().endswith(".mr"):
                matches.append(os.path.join(root, f))

    # 4. Check user Downloads folder as fallback
    if not matches:
        downloads_dir = os.path.expanduser("~/Downloads")
        if os.path.exists(downloads_dir):
            for root, _, files in os.walk(downloads_dir):
                for f in files:
                    if f.lower() == filename_to_match.lower():
                        matches.append(os.path.join(root, f))
                    elif clean_query.lower() in f.lower() and f.lower().endswith(".mr"):
                        matches.append(os.path.join(root, f))

    if matches:
        return os.path.abspath(matches[0])

    return None


def parse_instruction(text: str, base_dir: str = BASE_DIR) -> Optional[RecordInstruction]:
    """
    Parses natural language, shorthand, or structured instructions into a RecordInstruction.
    Examples:
        - "record the engine file assets/engines/mercedes/sls_amg_gt3_m159.mr on RPM 4000 for 3 seconds"
        - "record sls_amg_gt3_m159 on RPM 4000 for 3 seconds"
        - "record 03_2jz at 6000 rpm for 5s"
        - "record 'formula_1_v10_v3.mr' on RPM 12000 for 4 sec"
        - "record musical_v8 3300 3"
        - "assets/engines/mercedes/sls_amg_gt3_m159.mr, 4000, 3"
    """
    line = text.strip()
    if not line or line.startswith("#") or line.startswith("//"):
        return None

    eng_query = None
    rpm_val = None
    dur_val = None
    throttle = "r"
    output_name = None

    # Check for optional throttle key or output overrides in text: [throttle=w] or [out=take.wav]
    throttle_match = re.search(r'\[throttle\s*=\s*([qwer])\]', line, re.IGNORECASE)
    if throttle_match:
        throttle = throttle_match.group(1).lower()
        line = re.sub(r'\[throttle\s*=\s*[qwer]\]', '', line, flags=re.IGNORECASE).strip()

    out_match = re.search(r'\[out(?:put)?\s*=\s*([^\]]+)\]', line, re.IGNORECASE)
    if out_match:
        output_name = out_match.group(1).strip()
        line = re.sub(r'\[out(?:put)?\s*=\s*[^\]]+\]', '', line, flags=re.IGNORECASE).strip()

    # Pattern 1: Natural English sentence
    # "record [the engine [file]] <engine> [on|at] [RPM] <rpm> [RPM] [for] <duration> [s|sec|seconds]"
    m = re.search(
        r'record\s+(?:the\s+)?(?:engine\s+)?(?:file\s+)?["\']?([^"\',]+?)["\']?\s+(?:on|at)\s+(?:RPM\s+)?(\d+)\s*(?:RPM)?\s+(?:for\s+)?(\d+(?:\.\d+)?)\s*(?:s|sec|seconds)?',
        line,
        re.IGNORECASE
    )
    if m:
        eng_query = m.group(1).strip()
        rpm_val = int(m.group(2))
        dur_val = float(m.group(3))

    # Pattern 2: Key-value: "<engine>: <rpm> RPM, <duration>s"
    if not eng_query:
        m = re.search(r'["\']?([^"\',:]+?)["\']?\s*:\s*(\d+)\s*(?:RPM)?\s*,\s*(\d+(?:\.\d+)?)\s*(?:s|sec)?', line, re.IGNORECASE)
        if m:
            eng_query = m.group(1).strip()
            rpm_val = int(m.group(2))
            dur_val = float(m.group(3))

    # Pattern 3: Compact format: "record <engine> <rpm> <duration>"
    if not eng_query:
        m = re.search(r'record\s+["\']?([^"\',]+?)["\']?\s+(\d+)\s+(\d+(?:\.\d+)?)', line, re.IGNORECASE)
        if m:
            eng_query = m.group(1).strip()
            rpm_val = int(m.group(2))
            dur_val = float(m.group(3))

    # Pattern 4: CSV / Delimited: "<engine>, <rpm>, <duration>"
    if not eng_query:
        parts = [p.strip() for p in re.split(r'[,;|\t]+', line)]
        if len(parts) >= 3:
            p1_clean = parts[1].lower().replace("rpm", "").strip()
            p2_clean = parts[2].lower().replace("seconds", "").replace("sec", "").replace("s", "").strip()
            if p1_clean.isdigit():
                eng_query = parts[0].strip("\"' ")
                rpm_val = int(p1_clean)
                try:
                    dur_val = float(p2_clean)
                except ValueError:
                    dur_val = 3.0

    if not eng_query or rpm_val is None or dur_val is None:
        return None

    resolved = resolve_engine_file(eng_query, base_dir)
    return RecordInstruction(
        raw_instruction=text,
        engine_query=eng_query,
        resolved_engine_path=resolved or eng_query,
        target_rpm=rpm_val,
        duration_seconds=dur_val,
        output_filename=output_name,
        throttle_key=throttle
    )


def parse_instructions_from_text(text: str) -> List[RecordInstruction]:
    """Parses a multi-line string or JSON array into a list of RecordInstructions."""
    text = text.strip()
    if not text:
        return []

    # Try JSON array first
    if (text.startswith("[") and text.endswith("]")) or (text.startswith("{") and text.endswith("}")):
        try:
            data = json.loads(text)
            if isinstance(data, dict):
                data = [data]
            instructions = []
            for item in data:
                eng = item.get("engine") or item.get("file")
                rpm = int(item.get("rpm", 4000))
                dur = float(item.get("duration", 3.0))
                out = item.get("output")
                thr = item.get("throttle", "r")
                resolved = resolve_engine_file(eng) if eng else None
                instructions.append(RecordInstruction(
                    raw_instruction=str(item),
                    engine_query=eng,
                    resolved_engine_path=resolved or eng,
                    target_rpm=rpm,
                    duration_seconds=dur,
                    output_filename=out,
                    throttle_key=thr
                ))
            return instructions
        except Exception:
            pass

    # Line by line
    instructions = []
    for line in text.splitlines():
        ins = parse_instruction(line)
        if ins:
            instructions.append(ins)
    return instructions


def parse_instructions_file(filepath: str) -> List[RecordInstruction]:
    """Reads instructions from a text or JSON file."""
    if not os.path.exists(filepath):
        raise FileNotFoundError(f"Instructions file not found: {filepath}")
    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()
    return parse_instructions_from_text(content)


def get_engine_sim_pid() -> Optional[int]:
    """Finds PID of running engine-sim-app.exe."""
    try:
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


def kill_existing_engine_sim():
    """Cleanly terminates any previously running engine-sim-app.exe processes."""
    pid = get_engine_sim_pid()
    if pid:
        try:
            subprocess.run(["taskkill", "/F", "/PID", str(pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(0.5)
        except Exception:
            pass


def bring_window_to_front(hwnd) -> bool:
    """Forces the target window to the foreground and active state."""
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32

    try:
        user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0, 0x0001 | 0x0002)  # HWND_TOPMOST
        user32.SetWindowPos(hwnd, -2, 0, 0, 0, 0, 0x0001 | 0x0002)  # HWND_NOTOPMOST

        fore_hwnd = user32.GetForegroundWindow()
        fore_thread = user32.GetWindowThreadProcessId(fore_hwnd, None) if fore_hwnd else 0
        app_thread = kernel32.GetCurrentThreadId()
        target_thread = user32.GetWindowThreadProcessId(hwnd, None)

        if fore_thread:
            user32.AttachThreadInput(app_thread, fore_thread, True)
        user32.AttachThreadInput(app_thread, target_thread, True)

        user32.AllowSetForegroundWindow(-1)
        user32.SetForegroundWindow(hwnd)
        user32.SetActiveWindow(hwnd)
        user32.SetFocus(hwnd)

        if fore_thread:
            user32.AttachThreadInput(app_thread, fore_thread, False)
        user32.AttachThreadInput(app_thread, target_thread, False)

        # Send WM_ACTIVATE and WM_SETFOCUS messages
        WM_ACTIVATE = 0x0006
        WM_SETFOCUS = 0x0007
        WA_ACTIVE = 1
        user32.SendMessageW(hwnd, WM_ACTIVATE, WA_ACTIVE, 0)
        user32.SendMessageW(hwnd, WM_SETFOCUS, 0, 0)
        return True
    except Exception:
        return False


def prepare_engine_runner(engine_file_path: str, target_rpm: int) -> str:
    """
    Creates an auto-tuned engine runner that configures the dynamometer to
    precisely lock the target RPM with full dyno load.
    Saves runner directly in the engine's folder to preserve all relative imports.
    """
    with open(engine_file_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()

    # 1. Dyno hold configuration for target RPM
    dyno_inject = f"\n        dyno_min_speed: {target_rpm} * units.rpm,\n        dyno_max_speed: {target_rpm} * units.rpm,\n"

    if "dyno_min_speed" in content:
        content = re.sub(r'dyno_min_speed\s*:\s*[^;,]+[;,]', f'dyno_min_speed: {target_rpm} * units.rpm,', content)
    if "dyno_max_speed" in content:
        content = re.sub(r'dyno_max_speed\s*:\s*[^;,]+[;,]', f'dyno_max_speed: {target_rpm} * units.rpm,', content)
    if "dyno_min_speed" not in content and "dyno_max_speed" not in content:
        content = re.sub(r'((?:piston_)?engine\s+engine\s*\()', r'\1' + dyno_inject, content, count=1)

    # 2. Check and ensure redline is not lower than target RPM
    redline_match = re.search(r'redline\s*:\s*(\d+)\s*\*\s*units\.rpm', content)
    if redline_match:
        cur_redline = int(redline_match.group(1))
        if cur_redline <= target_rpm:
            safe_redline = target_rpm + 1500
            content = re.sub(r'redline\s*:\s*\d+\s*\*\s*units\.rpm', f'redline: {safe_redline} * units.rpm', content)

    # Write runner in same directory as target engine
    engine_dir = os.path.dirname(engine_file_path)
    runner_path = os.path.join(engine_dir, f"_auto_runner_{target_rpm}rpm.mr")

    with open(runner_path, "w", encoding="utf-8") as f:
        f.write(content)

    return runner_path


def execute_instruction(
    instruction: RecordInstruction,
    status_callback=None
) -> Dict[str, Any]:
    """
    Executes a single recording instruction:
    1. Prepares runner with exact RPM dyno lock
    2. Launches simulator
    3. Starts engine & engages dyno hold
    4. Records isolated audio for specified duration
    5. Saves lossless WAV file
    """
    def log(msg):
        print(msg)
        if status_callback:
            status_callback(msg)

    if not os.path.exists(instruction.resolved_engine_path):
        err = f"Engine file not found: {instruction.engine_query}"
        log(f"[!] {err}")
        return {"success": False, "error": err}

    log(f"\n" + "=" * 65)
    log(f"  RECORDING INSTRUCTION")
    log(f"  Engine:   {os.path.basename(instruction.resolved_engine_path)}")
    log(f"  Target:   {instruction.target_rpm} RPM")
    log(f"  Duration: {instruction.duration_seconds:.1f} seconds")
    log(f"=" * 65)

    # Build output filename if not provided
    if instruction.output_filename:
        out_filename = instruction.output_filename
        if not out_filename.lower().endswith(".wav"):
            out_filename += ".wav"
    else:
        eng_stem = os.path.splitext(os.path.basename(instruction.resolved_engine_path))[0]
        timestamp = time.strftime("%Y%m%d_%H%M%S")
        out_filename = f"{eng_stem}_{instruction.target_rpm}rpm_{instruction.duration_seconds:.1f}s_{timestamp}.wav"

    output_path = os.path.join(RECORDINGS_DIR, out_filename)

    # Clean up previous instance
    kill_existing_engine_sim()

    # Prepare runner
    runner_file = prepare_engine_runner(instruction.resolved_engine_path, instruction.target_rpm)

    # Point session_info.tmp to this runner
    try:
        with open(SESSION_INFO_PATH, "w") as f:
            f.write(runner_file + "\n")
    except Exception as e:
        log(f"[!] Warning: Could not write session_info.tmp: {e}")

    # Launch simulator
    log("[1/5] Launching Engine Simulator...")
    sim_proc = subprocess.Popen([SIM_EXE_PATH], cwd=BIN_DIR)
    time.sleep(1.8)

    # Locate window
    hwnd = None
    win = None
    for _ in range(15):
        wins = [w for w in gw.getAllWindows() if "Engine Sim" in w.title]
        if wins:
            win = wins[0]
            hwnd = getattr(win, "_hWnd", None)
            break
        time.sleep(0.3)

    if not hwnd or not win:
        sim_proc.kill()
        if os.path.exists(runner_file):
            os.remove(runner_file)
        err = "Could not detect Engine Simulator window."
        log(f"[!] {err}")
        return {"success": False, "error": err}

    bring_window_to_front(hwnd)
    time.sleep(0.5)

    if HAS_DIRECTINPUT:
        # Click window center to ensure focus
        cx = win.left + win.width // 2
        cy = win.top + win.height // 2
        pydirectinput.click(cx, cy)
        time.sleep(0.3)

    target_pid = sim_proc.pid

    # 1. Crank starter to start engine
    log("[2/5] Starting engine (cranking starter 's')...")
    if HAS_DIRECTINPUT:
        pydirectinput.keyDown('s')
        time.sleep(1.6)
        pydirectinput.keyUp('s')
        time.sleep(0.8)

    # 2. Engage dyno hold at target RPM
    log(f"[3/5] Locking dyno at {instruction.target_rpm} RPM ('d' + 'h')...")
    if HAS_DIRECTINPUT:
        pydirectinput.press('d')
        time.sleep(0.15)
        pydirectinput.press('h')
        time.sleep(0.15)

    # 3. Apply throttle against dyno
    log(f"[4/5] Applying throttle ('{instruction.throttle_key}')...")
    if HAS_DIRECTINPUT:
        pydirectinput.keyDown(instruction.throttle_key)
        time.sleep(0.5)

    # 4. Record audio
    log(f"[5/5] Recording {instruction.duration_seconds:.1f}s isolated audio to:\n      {output_path}...")
    rec_proc = None
    use_native = os.path.exists(NATIVE_RECORDER_PATH) and target_pid

    if use_native:
        rec_proc = subprocess.Popen(
            [NATIVE_RECORDER_PATH, str(target_pid), output_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            cwd=BASE_DIR
        )
        time.sleep(instruction.duration_seconds)
        try:
            rec_proc.communicate(input="\n", timeout=2.5)
        except Exception:
            try:
                rec_proc.kill()
            except Exception:
                pass
    else:
        # Fallback to system loopback capture
        recorder = get_loopback_recorder()
        if recorder:
            SAMPLE_RATE = 44100
            num_frames = int(SAMPLE_RATE * instruction.duration_seconds)
            data = recorder.record(numframes=num_frames, samplerate=SAMPLE_RATE)
            sf.write(output_path, data, SAMPLE_RATE)
        else:
            time.sleep(instruction.duration_seconds)

    # Release throttle & dyno
    if HAS_DIRECTINPUT:
        pydirectinput.keyUp(instruction.throttle_key)
        time.sleep(0.1)
        pydirectinput.press('d')

    # Terminate simulator
    try:
        sim_proc.terminate()
        sim_proc.wait(timeout=2.0)
    except Exception:
        sim_proc.kill()

    # Clean up runner
    if os.path.exists(runner_file):
        try:
            os.remove(runner_file)
        except Exception:
            pass

    # Verify recording
    if os.path.exists(output_path) and os.path.getsize(output_path) > 1000:
        file_size_kb = os.path.getsize(output_path) / 1024
        try:
            data, sr = sf.read(output_path)
            max_amp = float(np.max(np.abs(data))) if 'np' in sys.modules else 1.0
            log(f"[OK] Successfully saved: {out_filename} ({file_size_kb:.0f} KB, {len(data)/sr:.1f}s)")
        except Exception:
            log(f"[OK] Successfully saved: {out_filename} ({file_size_kb:.0f} KB)")
        return {
            "success": True,
            "output_path": output_path,
            "filename": out_filename,
            "size_kb": file_size_kb,
            "rpm": instruction.target_rpm,
            "duration": instruction.duration_seconds
        }
    else:
        err = f"Recording file was not generated or empty at: {output_path}"
        log(f"[!] {err}")
        return {"success": False, "error": err}


def execute_batch(instructions: List[RecordInstruction], status_callback=None) -> List[Dict[str, Any]]:
    """Executes a list of RecordInstructions sequentially."""
    results = []
    total = len(instructions)
    print(f"\n==================================================")
    print(f"  STARTING BATCH RECORDING ({total} instruction{'s' if total != 1 else ''})")
    print(f"==================================================")

    for idx, ins in enumerate(instructions, 1):
        if status_callback:
            status_callback(f"Running [{idx}/{total}]: {ins.engine_query} @ {ins.target_rpm} RPM...")
        res = execute_instruction(ins, status_callback)
        results.append(res)
        time.sleep(1.0)

    successes = sum(1 for r in results if r.get("success"))
    print(f"\n" + "=" * 65)
    print(f"  BATCH COMPLETED: {successes}/{total} successful recordings.")
    print(f"  Directory: {RECORDINGS_DIR}")
    print(f"=" * 65)
    return results


def list_available_engines(base_dir: str = BASE_DIR):
    """Prints all engine .mr files available in the project."""
    engines_dir = os.path.join(base_dir, "assets", "engines")
    files = glob.glob(os.path.join(engines_dir, "**", "*.mr"), recursive=True)
    print(f"\nAvailable Engine Scripts ({len(files)} found in assets/engines):")
    for f in sorted(files):
        rel = os.path.relpath(f, base_dir)
        stem = os.path.splitext(os.path.basename(f))[0]
        print(f"  - {stem:<28} ({rel})")
    print()


def interactive_cli():
    """Interactive command-line mode."""
    print("=" * 65)
    print("    ENGINE SIMULATOR - AUTOMATED RECORDER")
    print("=" * 65)
    print("Pass instructions to automatically play and record engines.")
    print("Example instruction formats:")
    print("  record the engine file sls_amg_gt3_m159 on RPM 4000 for 3 seconds")
    print("  record 03_2jz on RPM 6000 for 5 seconds")
    print("  record musical_v8 at 3300 RPM for 3 sec")
    print("\nCommands:")
    print("  'list'  - list all available engines")
    print("  'run'   - execute queued instructions")
    print("  'q'     - quit")
    print("=" * 65 + "\n")

    queue = []
    while True:
        try:
            line = input(f"[{len(queue)} queued] Enter instruction: ").strip()
        except (KeyboardInterrupt, EOFError):
            break

        if not line:
            continue
        if line.lower() in ("q", "quit", "exit"):
            break
        if line.lower() == "list":
            list_available_engines()
            continue
        if line.lower() == "run":
            if not queue:
                print("[!] Queue is empty. Enter an instruction first.")
                continue
            execute_batch(queue)
            queue.clear()
            continue

        ins = parse_instruction(line)
        if ins:
            if not os.path.exists(ins.resolved_engine_path):
                print(f"[!] Warning: Could not locate engine '{ins.engine_query}'.")
                print("    Type 'list' to see all valid engine names.")
            else:
                queue.append(ins)
                print(f"[OK] Added: {os.path.basename(ins.resolved_engine_path)} @ {ins.target_rpm} RPM for {ins.duration_seconds:.1f}s")
                ask_run = input("  Run now? [Y/n]: ").strip().lower()
                if ask_run in ("", "y", "yes"):
                    execute_batch(queue)
                    queue.clear()
        else:
            print("[!] Could not parse instruction. Example format:")
            print("    record the engine file <engine> on RPM <rpm> for <duration> seconds")


def main():
    parser = argparse.ArgumentParser(description="Engine Simulator Automated Audio Recorder")
    parser.add_argument("instruction", nargs="?", help="Direct instruction string (e.g. 'record sls_amg_gt3_m159 on RPM 4000 for 3 seconds')")
    parser.add_argument("--file", "-f", help="Path to text or JSON file containing instructions")
    parser.add_argument("--engine", "-e", help="Engine name or .mr path")
    parser.add_argument("--rpm", "-r", type=int, help="Target RPM (e.g. 4000)")
    parser.add_argument("--duration", "-d", type=float, default=3.0, help="Hold duration in seconds (default 3.0)")
    parser.add_argument("--output", "-o", help="Custom output filename (.wav)")
    parser.add_argument("--list", action="store_true", help="List all available engines in project")

    args = parser.parse_args()

    if args.list:
        list_available_engines()
        return

    if args.file:
        instructions = parse_instructions_file(args.file)
        if not instructions:
            print(f"[!] No valid instructions parsed from {args.file}")
            return
        execute_batch(instructions)
        return

    if args.engine and args.rpm:
        resolved = resolve_engine_file(args.engine)
        ins = RecordInstruction(
            raw_instruction=f"record {args.engine} on RPM {args.rpm} for {args.duration} seconds",
            engine_query=args.engine,
            resolved_engine_path=resolved or args.engine,
            target_rpm=args.rpm,
            duration_seconds=args.duration,
            output_filename=args.output
        )
        execute_batch([ins])
        return

    if args.instruction:
        ins = parse_instruction(args.instruction)
        if ins:
            execute_batch([ins])
        else:
            print(f"[!] Could not parse instruction: {args.instruction}")
            print("    Example: record the engine file sls_amg_gt3_m159 on RPM 4000 for 3 seconds")
        return

    interactive_cli()


if __name__ == "__main__":
    main()
