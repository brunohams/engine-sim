import subprocess
import time
import os
import ctypes
from ctypes import wintypes

# Define the shared memory structure matching C++
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
    h_proc = kernel32.OpenProcess(PROCESS_ALL_ACCESS, False, pid)
    if not h_proc:
        raise RuntimeError(f"OpenProcess failed: {ctypes.get_last_error()}")
    
    dll_bytes = dll_path.encode('utf-8') + b'\x00'
    remote_mem = kernel32.VirtualAllocEx(h_proc, None, len(dll_bytes), MEM_COMMIT | MEM_RESERVE, PAGE_READWRITE)
    if not remote_mem:
        kernel32.CloseHandle(h_proc)
        raise RuntimeError(f"VirtualAllocEx failed: {ctypes.get_last_error()}")
        
    written = ctypes.c_size_t(0)
    if not kernel32.WriteProcessMemory(h_proc, remote_mem, dll_bytes, len(dll_bytes), ctypes.byref(written)):
        kernel32.CloseHandle(h_proc)
        raise RuntimeError(f"WriteProcessMemory failed: {ctypes.get_last_error()}")
        
    h_k32 = kernel32.GetModuleHandleA(b"kernel32.dll")
    load_lib = kernel32.GetProcAddress(h_k32, b"LoadLibraryA")
    
    h_thread = kernel32.CreateRemoteThread(h_proc, None, 0, load_lib, remote_mem, 0, None)
    if not h_thread:
        kernel32.CloseHandle(h_proc)
        raise RuntimeError(f"CreateRemoteThread failed: {ctypes.get_last_error()}")
        
    kernel32.WaitForSingleObject(h_thread, 5000)
    kernel32.CloseHandle(h_thread)
    kernel32.CloseHandle(h_proc)
    print("Injected hook DLL successfully!")

def main():
    os.makedirs("recordings", exist_ok=True)
    
    # 1. Point engine simulator to Mercedes SLS AMG GT3
    engine_path = os.path.abspath("assets/engines/mercedes/sls_amg_gt3_m159.mr")
    with open("bin/session_info.tmp", "w") as f:
        f.write(engine_path)

    # 2. Launch engine-sim-app.exe
    app_path = os.path.abspath("bin/engine-sim-app.exe")
    proc = subprocess.Popen([app_path], cwd="bin")
    print(f"Launched Engine Sim, PID={proc.pid}")
    time.sleep(1.0)

    # 3. Inject hook DLL
    dll_path = os.path.abspath("bin/engine_hook.dll")
    inject_dll(proc.pid, dll_path)
    time.sleep(0.5)

    # 4. Connect to shared memory bridge
    h_map = kernel32.OpenFileMappingA(FILE_MAP_ALL_ACCESS, False, b"Local\\EngineSimBridge")
    retries = 0
    while not h_map and retries < 20:
        time.sleep(0.1)
        h_map = kernel32.OpenFileMappingA(FILE_MAP_ALL_ACCESS, False, b"Local\\EngineSimBridge")
        retries += 1
    
    if not h_map:
        proc.terminate()
        raise RuntimeError("Failed to open EngineSimBridge shared memory!")

    p_bridge = kernel32.MapViewOfFile(h_map, FILE_MAP_ALL_ACCESS, 0, 0, ctypes.sizeof(SimBridgeData))
    bridge = SimBridgeData.from_address(p_bridge)
    print(f"Connected to Bridge! Magic=0x{bridge.magic:X}")

    test_rpms = [2000, 4000]

    for target_rpm in test_rpms:
        print(f"\n---> Setting Target RPM: {target_rpm} <---")
        bridge.status = 0
        bridge.stableFrames = 0
        bridge.targetRpm = target_rpm
        bridge.throttle = 1.0

        # Wait for status == 3 (STABLE & READY)
        t0 = time.time()
        stable = False
        while time.time() - t0 < 8.0:
            cur_rpm = bridge.currentRpm
            status = bridge.status
            print(f"Live Status: {status}, Current RPM: {cur_rpm:.1f} (target: {target_rpm})", end='\r')
            if status == 3:
                stable = True
                break
            time.sleep(0.1)
        print()

        if stable:
            print(f"Engine is STABLE at {bridge.currentRpm:.1f} RPM! Starting 3.0s recording...")
            wav_path = os.path.abspath(f"recordings/sls_amg_{target_rpm}rpm.wav")
            rec_proc = subprocess.run([
                os.path.abspath("bin/process_recorder.exe"),
                str(proc.pid),
                wav_path,
                "3.0"
            ], capture_output=True, text=True)
            print(f"Recording output: {rec_proc.stdout.strip()}")
            if os.path.exists(wav_path):
                print(f"Saved: {wav_path} (Size: {os.path.getsize(wav_path)} bytes)")
        else:
            print(f"Warning: Engine did not reach stability within timeout.")

    proc.terminate()
    proc.wait()
    kernel32.UnmapViewOfFile(p_bridge)
    kernel32.CloseHandle(h_map)
    print("\nTest completed successfully!")

if __name__ == "__main__":
    main()
