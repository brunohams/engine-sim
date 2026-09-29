import subprocess
import time
import os
import ctypes
from ctypes import wintypes

# 1. Update assets/main.mr to point to formula_1_v10_v3.mr
main_mr_path = os.path.abspath("assets/main.mr")
content = '''import "engine_sim.mr"
import "themes/default.mr"

import "engines/formula_1_v10_v3.mr"

use_default_theme()
main()
'''
with open(main_mr_path, "w", encoding="utf-8") as f:
    f.write(content)

print("Updated assets/main.mr to formula_1_v10_v3.mr")

# 2. Launch engine-sim-app.exe
app_exe = os.path.abspath("bin/engine-sim-app.exe")
hook_dll = os.path.abspath("bin/engine_hook.dll")

proc = subprocess.Popen([app_exe], cwd="bin")
print(f"Launched engine-sim-app.exe, PID={proc.pid}")
time.sleep(1.2)

# 3. Inject hook DLL
kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
PROCESS_ALL_ACCESS = 0x1F0FFF
MEM_COMMIT = 0x1000
MEM_RESERVE = 0x2000
PAGE_READWRITE = 0x04
FILE_MAP_ALL_ACCESS = 0xF001F

h_proc = kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, proc.pid)
dll_bytes = hook_dll.encode('utf-8') + b'\x00'
remote_mem = kernel32.VirtualAllocEx(h_proc, None, len(dll_bytes), MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE)
written = ctypes.c_size_t(0)
kernel32.WriteProcessMemory(h_proc, remote_mem, dll_bytes, len(dll_bytes), ctypes.byref(written))
h_k32 = kernel32.GetModuleHandleA(b"kernel32.dll")
load_lib = kernel32.GetProcAddress(h_k32, b"LoadLibraryA")
h_thread = kernel32.CreateRemoteThread(h_proc, None, 0, load_lib, remote_mem, 0, None)
kernel32.WaitForSingleObject(h_thread, 5000)
kernel32.CloseHandle(h_thread)
kernel32.CloseHandle(h_proc)
print("Injected hook DLL.")

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

time.sleep(0.5)
h_map = kernel32.OpenFileMappingA(FILE_MAP_ALL_ACCESS, False, b"Local\\EngineSimBridge")
retries = 0
while not h_map and retries < 20:
    time.sleep(0.1)
    h_map = kernel32.OpenFileMappingA(FILE_MAP_ALL_ACCESS, False, b"Local\\EngineSimBridge")
    retries += 1

if not h_map:
    proc.terminate()
    raise RuntimeError("Failed to connect to bridge mapping!")

p_bridge = kernel32.MapViewOfFile(h_map, FILE_MAP_ALL_ACCESS, 0, 0, ctypes.sizeof(SimBridgeData))
bridge = SimBridgeData.from_address(p_bridge)

print(f"Connected to Bridge! Magic: 0x{bridge.magic:X}")

# Set target RPM to 13,000
bridge.status = 0
bridge.stableFrames = 0
bridge.targetRpm = 13000
bridge.throttle = 1.0

for i in range(12):
    print(f"[{i*0.5:.1f}s] Status: {bridge.status} | Current RPM: {bridge.currentRpm:.1f} | Frame: {bridge.frameCount}")
    time.sleep(0.5)

proc.terminate()
proc.wait()
kernel32.UnmapViewOfFile(p_bridge)
kernel32.CloseHandle(h_map)
print("Finished test.")
