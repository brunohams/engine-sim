"""
Engine Simulator Automated Audio Recorder & Controller
-------------------------------------------------------
Designed for sampling musical notes, revving sweeps, and steady RPM tones
directly from Engine Simulator into lossless WAV audio files.
"""

import os
import sys
import time
import argparse
import threading
import subprocess
from datetime import datetime

import soundcard as sc
import soundfile as sf
import pydirectinput
import pygetwindow as gw

# Ensure PyDirectInput failsafes and slight pauses are configured
pydirectinput.PAUSE = 0.05
pydirectinput.FAILSAFE = False

SAMPLE_RATE = 48000
RECORDINGS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "recordings")
SIM_EXE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bin", "engine-sim-app.exe")


def get_loopback_recorder():
    """Finds the loopback audio device for the system's active speakers."""
    loopbacks = [m for m in sc.all_microphones(include_loopback=True) if m.isloopback]
    if not loopbacks:
        raise RuntimeError("No audio loopback device found. Ensure speakers/headphones are connected.")
    
    # Try to match default speaker name
    speaker = sc.default_speaker()
    matched = [m for m in loopbacks if speaker.name in m.name]
    if matched:
        return matched[0]
    return loopbacks[0]


NATIVE_RECORDER_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bin", "process_recorder.exe")

def get_engine_sim_pid():
    import ctypes
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

def record_audio_stream(filename: str, duration_seconds: float, target_pid=None):
    """Records audio from isolated Engine Sim process if available, or system loopback as fallback."""
    os.makedirs(RECORDINGS_DIR, exist_ok=True)
    full_path = os.path.join(RECORDINGS_DIR, filename)

    if not target_pid:
        target_pid = get_engine_sim_pid()

    if target_pid and os.path.exists(NATIVE_RECORDER_PATH):
        print(f"[*] Recording isolated audio from Engine Sim (PID {target_pid}) for {duration_seconds:.1f}s...")
        proc = subprocess.Popen(
            [NATIVE_RECORDER_PATH, str(target_pid), full_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        time.sleep(duration_seconds)
        try:
            proc.communicate(input="\n", timeout=2.0)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        print(f"\n[OK] Isolated Recording saved to:\n    {full_path}")
        return full_path

    # Fallback to system loopback
    recorder = get_loopback_recorder()
    num_frames = int(SAMPLE_RATE * duration_seconds)
    print(f"[*] Recording {duration_seconds:.1f}s via system loopback [{recorder.name}]...")
    data = recorder.record(numframes=num_frames, samplerate=SAMPLE_RATE)
    sf.write(full_path, data, SAMPLE_RATE)
    print(f"\n[OK] Recording saved to:\n    {full_path}")
    return full_path


def find_or_launch_engine_sim(auto_launch=True):
    """Finds the Engine Simulator window or optionally launches it."""
    windows = [w for w in gw.getAllWindows() if "Engine Sim" in w.title]
    if windows:
        win = windows[0]
        try:
            if win.isMinimized:
                win.restore()
            win.activate()
            time.sleep(0.5)
            print(f"[OK] Focused window: '{win.title}'")
            return win
        except Exception as e:
            print(f"[!] Note on focusing window: {e}")
            return win

    if auto_launch and os.path.exists(SIM_EXE_PATH):
        print("[*] Engine Simulator not running. Launching engine-sim-app.exe...")
        subprocess.Popen([SIM_EXE_PATH], cwd=os.path.dirname(SIM_EXE_PATH))
        # Wait up to 10 seconds for window to appear
        for _ in range(20):
            time.sleep(0.5)
            windows = [w for w in gw.getAllWindows() if "Engine Sim" in w.title]
            if windows:
                win = windows[0]
                try:
                    win.activate()
                except Exception:
                    pass
                time.sleep(1.0)
                print(f"[OK] Launched and focused: '{win.title}'")
                return win

    print("[!] Could not find or launch 'Engine Simulator' window.")
    return None


def crank_starter(duration=1.4):
    """Cranks the starter motor by pressing key 's'."""
    print("[*] Cranking starter (pressing 's')...")
    pydirectinput.keyDown('s')
    time.sleep(duration)
    pydirectinput.keyUp('s')


def record_rev_sweep(throttle_key='r', rev_duration=2.5, total_duration=8.0, output_name=None):
    """
    Starts engine, idles, revs engine using throttle_key ('r' = 100%, 'e' = 20%, 'w' = 10%),
    releases throttle, and records the whole sequence.
    """
    win = find_or_launch_engine_sim()
    if not win:
        return

    if not output_name:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_name = f"rev_sweep_{throttle_key}_{timestamp}.wav"

    print(f"\n==========================================")
    print(f"  RECORDING REV SWEEP")
    print(f"  Throttle Key: '{throttle_key}' | Rev Time: {rev_duration}s | Total: {total_duration}s")
    print(f"==========================================\n")

    # Start audio capture in background thread
    rec_thread = threading.Thread(
        target=record_audio_stream,
        args=(output_name, total_duration)
    )
    rec_thread.start()

    time.sleep(0.5)
    # Crank starter
    crank_starter(1.4)

    # Idle settling
    print("[*] Idling...")
    time.sleep(1.5)

    # Revving
    print(f"[*] Applying throttle ('{throttle_key}') for {rev_duration}s...")
    pydirectinput.keyDown(throttle_key)
    time.sleep(rev_duration)
    pydirectinput.keyUp(throttle_key)
    print("[*] Released throttle. Waiting for audio recording to complete...")

    rec_thread.join()


def record_stable_rpm(throttle_key='w', hold_duration=6.0, note_label=None, output_name=None):
    """
    Starts engine, holds a steady throttle or dyno speed, recording sustained audio for note sampling.
    """
    win = find_or_launch_engine_sim()
    if not win:
        return

    total_duration = hold_duration + 3.5

    if not output_name:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        prefix = f"note_{note_label}_" if note_label else f"stable_{throttle_key}_"
        output_name = f"{prefix}{timestamp}.wav"

    print(f"\n==========================================")
    print(f"  RECORDING STABLE RPM / NOTE SAMPLE")
    print(f"  Throttle Key: '{throttle_key}' | Hold: {hold_duration}s | File: {output_name}")
    print(f"==========================================\n")

    # Start audio capture
    rec_thread = threading.Thread(
        target=record_audio_stream,
        args=(output_name, total_duration)
    )
    rec_thread.start()

    time.sleep(0.5)
    # Crank starter
    crank_starter(1.4)
    time.sleep(1.0)

    # Hold throttle
    print(f"[*] Holding throttle ('{throttle_key}') for {hold_duration}s...")
    pydirectinput.keyDown(throttle_key)
    time.sleep(hold_duration)
    pydirectinput.keyUp(throttle_key)
    print("[*] Released throttle. Finishing recording...")

    rec_thread.join()


def calculate_rpm_for_note(note_name: str, cylinders=4):
    """Calculates the target RPM for a 4-stroke engine for a given musical note."""
    NOTES = {'C': -9, 'C#': -8, 'Db': -8, 'D': -7, 'D#': -6, 'Eb': -6,
             'E': -5, 'F': -4, 'F#': -3, 'Gb': -3, 'G': -2, 'G#': -1,
             'Ab': -1, 'A': 0, 'A#': 1, 'Bb': 1, 'B': 2}
    
    note_name = note_name.strip()
    pitch_class = note_name[:-1].capitalize()
    octave = int(note_name[-1])
    
    semitones_from_a4 = NOTES[pitch_class] + (octave - 4) * 12
    freq = 440.0 * (2.0 ** (semitones_from_a4 / 12.0))
    
    # 4-stroke formula: freq = (RPM / 60) * (cylinders / 2)
    rpm = freq * 60.0 / (cylinders / 2.0)
    return freq, rpm


def interactive_menu():
    """Interactive command-line interface."""
    print("=" * 60)
    print("    ENGINE SIMULATOR AUDIO RECORDING SUITE")
    print("=" * 60)
    print("1. Record Engine Rev Sweep (idle -> rev -> idle)")
    print("2. Record Stable RPM (steady hold for note sampling)")
    print("3. Musical Note to RPM Calculator (for 4-stroke engines)")
    print("4. Manual Free-form Recording (record system audio for N seconds)")
    print("Q. Quit")
    print("=" * 60)

    choice = input("\nEnter your choice (1-4, Q): ").strip().upper()

    if choice == '1':
        print("\nSelect throttle intensity for rev:")
        print("  w = 10% throttle (light rev)")
        print("  e = 20% throttle (medium rev)")
        print("  r = 100% throttle (full redline rev)")
        t_key = input("Choose key [default 'r']: ").strip().lower() or 'r'
        dur_str = input("Rev hold duration in seconds [default 2.5]: ").strip()
        dur = float(dur_str) if dur_str else 2.5
        record_rev_sweep(throttle_key=t_key, rev_duration=dur)

    elif choice == '2':
        print("\nSelect throttle intensity for steady RPM:")
        print("  q = 1% throttle (high idle)")
        print("  w = 10% throttle (cruising RPM)")
        print("  e = 20% throttle (mid RPM)")
        print("  r = 100% throttle (governed / max RPM)")
        t_key = input("Choose key [default 'w']: ").strip().lower() or 'w'
        dur_str = input("Hold duration in seconds [default 6.0]: ").strip()
        dur = float(dur_str) if dur_str else 6.0
        label = input("Optional note/sample label (e.g. C3, 3000rpm): ").strip()
        record_stable_rpm(throttle_key=t_key, hold_duration=dur, note_label=label)

    elif choice == '3':
        note = input("\nEnter note name (e.g. A2, C3, D4, E4): ").strip()
        cyls_str = input("Number of cylinders [default 4]: ").strip()
        cyls = int(cyls_str) if cyls_str else 4
        try:
            freq, rpm = calculate_rpm_for_note(note, cyls)
            print(f"\n[Note {note}]")
            print(f"  Target Frequency: {freq:.2f} Hz")
            print(f"  Target RPM for {cyls}-cylinder engine: {rpm:.0f} RPM")
            print(f"  Tip: You can set 'rev_limit: {int(rpm)} * units.rpm' in your .mr file")
            print(f"       and hold full throttle ('r') to lock this exact pitch!")
        except Exception as e:
            print(f"[!] Error calculating note: {e}")

    elif choice == '4':
        dur_str = input("\nEnter recording duration in seconds [default 10]: ").strip()
        dur = float(dur_str) if dur_str else 10.0
        fname = input("Output filename [e.g. manual_sample.wav]: ").strip() or "manual_sample.wav"
        record_audio_stream(fname, dur)


def main():
    parser = argparse.ArgumentParser(description="Engine Simulator Audio Recorder")
    parser.add_argument("--mode", choices=["rev", "stable", "manual", "calc"], help="Recording mode")
    parser.add_argument("--throttle", default="w", choices=["q", "w", "e", "r"], help="Throttle key to press")
    parser.add_argument("--duration", type=float, default=6.0, help="Hold duration in seconds")
    parser.add_argument("--output", type=str, default=None, help="Output WAV filename")
    parser.add_argument("--note", type=str, default=None, help="Musical note name (e.g. A3)")
    parser.add_argument("--cylinders", type=int, default=4, help="Engine cylinder count")

    args = parser.parse_args()

    if not args.mode:
        interactive_menu()
    elif args.mode == "rev":
        record_rev_sweep(throttle_key=args.throttle, rev_duration=args.duration, output_name=args.output)
    elif args.mode == "stable":
        record_stable_rpm(throttle_key=args.throttle, hold_duration=args.duration, note_label=args.note, output_name=args.output)
    elif args.mode == "manual":
        out = args.output or "manual_record.wav"
        record_audio_stream(out, args.duration)
    elif args.mode == "calc":
        if args.note:
            freq, rpm = calculate_rpm_for_note(args.note, args.cylinders)
            print(f"Note {args.note}: {freq:.2f} Hz -> {rpm:.0f} RPM ({args.cylinders}-cyl)")
        else:
            print("[!] Please provide --note (e.g. --note A3)")


if __name__ == "__main__":
    main()
