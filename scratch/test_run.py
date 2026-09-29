import subprocess
import time
import os
import ctypes
from ctypes import wintypes

kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)

PROCESS_ALL_ACCESS = 0x1F0FFF
MEM_COMMIT = 0x1000
MEM_RESERVE = 0x2000
PAGE_READWRITE = 0x04

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
    print("Injected successfully!")

# Set session info to Mercedes SLS AMG GT3 M159
engine_path = os.path.abspath("assets/engines/mercedes/sls_amg_gt3_m159.mr")
with open("bin/session_info.tmp", "w") as f:
    f.write(engine_path)

if os.path.exists("engine_hook.log"):
    os.remove("engine_hook.log")

app_path = os.path.abspath("bin/engine-sim-app.exe")
proc = subprocess.Popen([app_path], cwd="bin")
print(f"Launched engine-sim-app.exe with PID {proc.pid}")
time.sleep(1.0)

dll_path = os.path.abspath("bin/engine_hook.dll")
inject_dll(proc.pid, dll_path)

time.sleep(4.0)

proc.terminate()
proc.wait()

print("\n--- engine_hook.log ---")
if os.path.exists("engine_hook.log"):
    with open("engine_hook.log", "r") as f:
        print(f.read())
