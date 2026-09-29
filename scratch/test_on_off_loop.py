import subprocess
import time
import os
import wave
import numpy as np
import ctypes
from ctypes import wintypes

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

def create_perfect_loop(raw_wav_path, out_wav_path, rpm, target_duration=3.0, xfade_sec=0.25, lead_trim_sec=0.4):
    """
    Transforms raw recorded audio into a mathematically seamless audio loop.
    Trims initial lead buffer, aligns to nearest integer engine cycle period,
    and applies an equal-power crossfade between the tail and head.
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

    # Search in small window (+/- 0.5 cycle) for best phase alignment
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

    # Equal-power crossfade curve
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

def main():
    os.makedirs("recordings", exist_ok=True)
    engine_path = os.path.abspath("assets/engines/mercedes/sls_amg_gt3_m159.mr")

    with open("bin/session_info.tmp", "w") as f:
        f.write(engine_path)

    app_exe = os.path.abspath("bin/engine-sim-app.exe")
    recorder_exe = os.path.abspath("bin/process_recorder.exe")
    hook_dll = os.path.abspath("bin/engine_hook.dll")

    proc = subprocess.Popen([app_exe], cwd="bin")
    print(f"Launched Engine Sim, PID={proc.pid}")
    time.sleep(1.0)

    inject_dll(proc.pid, hook_dll)
    print("Injected hook DLL.")
    time.sleep(0.5)

    h_map = kernel32.OpenFileMappingA(FILE_MAP_ALL_ACCESS, False, b"Local\\EngineSimBridge")
    while not h_map:
        time.sleep(0.1)
        h_map = kernel32.OpenFileMappingA(FILE_MAP_ALL_ACCESS, False, b"Local\\EngineSimBridge")

    p_bridge = kernel32.MapViewOfFile(h_map, FILE_MAP_ALL_ACCESS, 0, 0, ctypes.sizeof(SimBridgeData))
    bridge = SimBridgeData.from_address(p_bridge)

    target_rpm = 2500
    takes = [
        ("On", 1.0),
        ("Off", 0.0),
    ]

    for suffix, thr in takes:
        print(f"\n==========================================")
        print(f"Targeting: {target_rpm} RPM | Throttle: {thr} ({suffix})")
        print(f"==========================================")

        bridge.status = 0
        bridge.stableFrames = 0
        bridge.targetRpm = target_rpm
        bridge.throttle = thr

        # 1. Wait for stability
        t0 = time.time()
        while time.time() - t0 < 8.0:
            if bridge.status == 3:
                break
            time.sleep(0.08)

        print(f"Engine reached stability at {bridge.currentRpm:.1f} RPM.")

        # 2. Settle Delay to prevent any audio leakage from prior state!
        settle_delay = 1.5
        print(f"Waiting {settle_delay}s settle delay for audio buffer clearance...")
        time.sleep(settle_delay)

        # 3. Record raw take (duration + 1.2s extra for lead trim and loop crossfade)
        raw_temp_wav = os.path.abspath(f"recordings/raw_temp_{target_rpm}_{suffix}.wav")
        final_wav = os.path.abspath(f"recordings/sls_amg_gt3_{target_rpm}rpm_{suffix}.wav")

        print("Recording audio...")
        rec = subprocess.run([
            recorder_exe,
            str(proc.pid),
            raw_temp_wav,
            "4.2"  # 3.0s target + 0.4s lead trim + 0.25s xfade + extra
        ], capture_output=True, text=True)

        print("Raw recording complete. Building perfect seamless loop...")
        loop_dur = create_perfect_loop(raw_temp_wav, final_wav, target_rpm, target_duration=3.0)
        
        if os.path.exists(raw_temp_wav):
            os.remove(raw_temp_wav)

        print(f"SUCCESS: Saved {final_wav}")
        print(f"Loop duration: {loop_dur:.3f}s | File size: {os.path.getsize(final_wav)} bytes")

    proc.terminate()
    proc.wait()
    kernel32.UnmapViewOfFile(p_bridge)
    kernel32.CloseHandle(h_map)
    print("\nTest completed successfully!")

if __name__ == "__main__":
    main()
