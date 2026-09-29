import subprocess
import time
import os
import sys
import ctypes
from ctypes import wintypes
import wave
import numpy as np

sys.path.insert(0, os.path.abspath("."))
import engine_recorder_backend as b

# 1. Update assets/main.mr to formula_1_v10_v3.mr
main_mr = os.path.abspath("assets/main.mr")
with open(main_mr, "w", encoding="utf-8") as f:
    f.write('import "engine_sim.mr"\nimport "themes/default.mr"\nimport "engines/formula_1_v10_v3.mr"\nuse_default_theme()\nmain()\n')

print("Updated assets/main.mr to formula_1_v10_v3.mr")

# 2. Launch engine-sim-app.exe
app_exe = os.path.abspath("bin/engine-sim-app.exe")
hook_dll = os.path.abspath("bin/engine_hook.dll")
recorder_exe = os.path.abspath("bin/process_recorder.exe")

proc = subprocess.Popen([app_exe], cwd="bin")
print(f"Launched engine-sim-app.exe, PID={proc.pid}")
time.sleep(1.2)

# 3. Inject hook
b.inject_dll(proc.pid, hook_dll)
print("Injected hook DLL.")
time.sleep(0.6)

kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
FILE_MAP_ALL_ACCESS = 0xF001F

h_map = kernel32.OpenFileMappingA(FILE_MAP_ALL_ACCESS, False, b"Local\\EngineSimBridge")
while not h_map:
    time.sleep(0.1)
    h_map = kernel32.OpenFileMappingA(FILE_MAP_ALL_ACCESS, False, b"Local\\EngineSimBridge")

p_bridge = kernel32.MapViewOfFile(h_map, FILE_MAP_ALL_ACCESS, 0, 0, ctypes.sizeof(b.SimBridgeData))
bridge = b.SimBridgeData.from_address(p_bridge)

print(f"Bridge connected: magic=0x{bridge.magic:X}")

target_rpms = [8000, 12000]

for target in target_rpms:
    print(f"\n---> Target: {target} RPM <---")
    bridge.status = 0
    bridge.stableFrames = 0
    bridge.targetRpm = target
    bridge.throttle = 1.0

    t0 = time.time()
    while time.time() - t0 < 8.0:
        print(f"Status: {bridge.status}, Cur RPM: {bridge.currentRpm:.1f}, Frames: {bridge.frameCount}", end="\r")
        if bridge.status == 3:
            break
        time.sleep(0.1)
    print()

    print(f"RPM locked at {bridge.currentRpm:.1f}. Waiting 1.5s settle delay...")
    time.sleep(1.5)

    raw_wav = os.path.abspath(f"recordings/raw_f1_{target}.wav")
    final_wav = os.path.abspath(f"recordings/f1_v10_{target}rpm_On.wav")

    print(f"Recording {target} RPM take...")
    subprocess.run([recorder_exe, str(proc.pid), raw_wav, "4.2"], capture_output=True, text=True)

    print("Building seamless loop...")
    dur = b.create_perfect_loop(raw_wav, final_wav, target, target_duration=3.0)
    if os.path.exists(raw_wav): os.remove(raw_wav)

    print(f"Saved: {final_wav} ({os.path.getsize(final_wav)} bytes, {dur:.2f}s)")

proc.terminate()
proc.wait()
kernel32.UnmapViewOfFile(p_bridge)
kernel32.CloseHandle(h_map)
print("\nAll F1 V10 takes finished successfully!")
