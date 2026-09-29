#include <windows.h>
#include <fstream>
#include <iostream>
#include <string>
#include <cmath>

#pragma pack(push, 8)
struct SimBridgeData {
    uint32_t magic;         // 0x53494D31 ('SIM1')
    int32_t command;        // 1 = active, 0 = idle
    int32_t targetRpm;      // Target RPM to hold
    double throttle;        // Throttle setting (0.0 to 1.0)
    
    int32_t status;         // 0 = uninit, 1 = starting, 2 = adjusting, 3 = stable (ready to record)
    double currentRpm;      // Live engine RPM
    int32_t frameCount;     // Frame counter
    int32_t stableFrames;   // Consecutive stable frames count
};
#pragma pack(pop)

static HANDLE g_hMapFile = NULL;
static SimBridgeData *g_bridge = NULL;
static std::ofstream g_log;

void Log(const char *msg) {
    if (g_log.is_open()) {
        g_log << msg << std::endl;
        g_log.flush();
    }
}

void InitSharedMemory() {
    g_hMapFile = CreateFileMappingA(
        INVALID_HANDLE_VALUE,
        NULL,
        PAGE_READWRITE,
        0,
        sizeof(SimBridgeData),
        "Local\\EngineSimBridge"
    );

    if (g_hMapFile != NULL) {
        g_bridge = (SimBridgeData *)MapViewOfFile(
            g_hMapFile,
            FILE_MAP_ALL_ACCESS,
            0,
            0,
            sizeof(SimBridgeData)
        );
        if (g_bridge != NULL) {
            g_bridge->magic = 0x53494D31;
            g_bridge->command = 1;
            g_bridge->targetRpm = 1000;
            g_bridge->throttle = 1.0;
            g_bridge->status = 0;
            g_bridge->currentRpm = 0.0;
            g_bridge->frameCount = 0;
            g_bridge->stableFrames = 0;
            Log("Shared memory bridge initialized.");
        }
    }
}

LONG WINAPI VectoredHandler(PEXCEPTION_POINTERS pExceptionInfo) {
    char buf[256];
    sprintf_s(buf, sizeof(buf), "CRASH: Code=0x%X at RIP=%p (RVA=0x%X)", 
              pExceptionInfo->ExceptionRecord->ExceptionCode,
              (void*)pExceptionInfo->ContextRecord->Rip,
              (uint32_t)((BYTE*)pExceptionInfo->ContextRecord->Rip - (BYTE*)GetModuleHandleA(NULL)));
    Log(buf);
    return EXCEPTION_CONTINUE_SEARCH;
}

static int g_frameCount = 0;

extern "C" void DoHookLogic(void *app) {
    g_frameCount++;

    void *simulator = nullptr;
    void *iceEngine = nullptr;

    __try {
        simulator = *(void **)((BYTE *)app + 0x1618);
        iceEngine = *(void **)((BYTE *)app + 0x1600);
    } __except(EXCEPTION_EXECUTE_HANDLER) {
        return;
    }

    if (!g_bridge) {
        InitSharedMemory();
    }

    if (simulator && iceEngine) {
        typedef double (*pfnGetRpm)(void *engine);
        typedef bool (*pfnGetIgnition)(void *engine);
        typedef void (*pfnSetIgnition)(void *engine, bool enabled);
        typedef void (*pfnSetSpeedControl)(void *engine, double control);

        // Virtual table slots:
        // Slot 15 = getRpm() const
        // Slot 21 = isIgnitionEnabled() const
        // Slot 22 = setIgnitionEnabled(bool)
        // Slot 3  = setSpeedControl(double)
        pfnGetRpm getRpm = (pfnGetRpm)(*(void ***)iceEngine)[15];
        pfnGetIgnition getIgnition = (pfnGetIgnition)(*(void ***)iceEngine)[21];
        pfnSetIgnition setIgnition = (pfnSetIgnition)(*(void ***)iceEngine)[22];
        pfnSetSpeedControl setSpeedControl = (pfnSetSpeedControl)(*(void ***)iceEngine)[3];

        double currentRpm = 0.0;
        bool ignitionOn = false;

        __try {
            currentRpm = getRpm(iceEngine);
            ignitionOn = getIgnition(iceEngine);
        } __except(EXCEPTION_EXECUTE_HANDLER) {}

        if (std::isnan(currentRpm) || std::isinf(currentRpm)) {
            currentRpm = 0.0;
        }

        __try {
            bool *pStarter = (bool *)((BYTE *)simulator + 0x1C0);
            bool *pDynoEnabled = (bool *)((BYTE *)simulator + 0xE1);
            bool *pDynoHold = (bool *)((BYTE *)simulator + 0xE0);
            double *pDynoSpeed = (double *)((BYTE *)simulator + 0xC0);
            double *pTargetThrottle = (double *)((BYTE *)app + 0x18);
            double *pCurrentThrottle = (double *)((BYTE *)app + 0x10);

            // Keep clutch pedal fully depressed
            *(double *)((BYTE *)app + 0x28) = 0.0;
            *(double *)((BYTE *)app + 0x30) = 0.0;

            // Read dynamic engine parameters directly from Engine object
            double starterSpeedRadS = *(double *)((BYTE *)iceEngine + 0xC0);
            double starterSpeedRpm = starterSpeedRadS / 0.10471975511965977;
            if (starterSpeedRpm < 300.0 || starterSpeedRpm > 12000.0 || std::isnan(starterSpeedRpm)) {
                starterSpeedRpm = 800.0;
            }

            int cmd = g_bridge ? g_bridge->command : 1;

            // Command 4: Engine Shutdown (Turn Off)
            if (cmd == 4) {
                *pStarter = false;
                *pDynoEnabled = false;
                *pDynoHold = false;
                *pTargetThrottle = 0.0;
                *pCurrentThrottle = 0.0;
                if (ignitionOn) {
                    setIgnition(iceEngine, false);
                }

                if (g_bridge) {
                    if (currentRpm < 25.0) {
                        g_bridge->status = 4; // Shutdown complete!
                    } else {
                        g_bridge->status = 2; // Decelerating / coasting down
                    }
                    g_bridge->currentRpm = currentRpm;
                    g_bridge->frameCount = g_frameCount;
                }
                return;
            }

            // All other commands require ignition ON
            if (!ignitionOn) {
                setIgnition(iceEngine, true);
            }

            double crankThreshold = starterSpeedRpm * 0.85;

            // Initial engine startup / cranking check
            if (g_frameCount < 45 || currentRpm < crankThreshold) {
                *pStarter = true;
                *pDynoEnabled = false;
                *pDynoHold = false;
                *pTargetThrottle = 0.4;
                *pCurrentThrottle = 0.4;

                if (g_bridge) {
                    g_bridge->status = 1; // starting/cranking
                    g_bridge->stableFrames = 0;
                }
            } else if (cmd == 2) {
                // Command 2: Engine Idle Mode
                *pStarter = false;
                *pDynoEnabled = true;
                *pDynoHold = true;
                *pDynoSpeed = starterSpeedRadS;
                *pTargetThrottle = 0.0;
                *pCurrentThrottle = 0.0;

                if (g_bridge) {
                    double tol = (std::max)(120.0, starterSpeedRpm * 0.05);
                    if (std::abs(currentRpm - starterSpeedRpm) < tol) {
                        g_bridge->stableFrames++;
                        if (g_bridge->stableFrames >= 20) {
                            g_bridge->status = 3; // Ready to record Idle
                        } else {
                            g_bridge->status = 2;
                        }
                    } else {
                        g_bridge->stableFrames = 0;
                        g_bridge->status = 2;
                    }
                }
            } else {
                // Command 1 or 3: Hold at target RPM with specified throttle (or Max RPM)
                int target = (int)starterSpeedRpm;
                double thr = 1.0;
                if (g_bridge) {
                    target = g_bridge->targetRpm;
                    if (target <= 0) target = (int)starterSpeedRpm;
                    thr = g_bridge->throttle;
                    if (thr < 0.0) thr = 0.0;
                    if (thr > 1.0) thr = 1.0;
                }

                double targetRadS = (double)target * 0.10471975511965977;

                *pStarter = false;
                *pDynoEnabled = true;
                *pDynoHold = true;
                *pDynoSpeed = targetRadS;

                *pTargetThrottle = thr;
                *pCurrentThrottle = thr;

                if (g_bridge) {
                    double tol = (std::max)(150.0, (double)target * 0.04);
                    if (std::abs(currentRpm - (double)target) < tol) {
                        g_bridge->stableFrames++;
                        if (g_bridge->stableFrames >= 20) {
                            g_bridge->status = 3; // Stable & ready to record
                        } else {
                            g_bridge->status = 2;
                        }
                    } else {
                        g_bridge->stableFrames = 0;
                        g_bridge->status = 2;
                    }
                }
            }

            if (g_bridge) {
                g_bridge->currentRpm = currentRpm;
                g_bridge->frameCount = g_frameCount;
            }
        } __except(EXCEPTION_EXECUTE_HANDLER) {
            Log("Exception setting engine state!");
        }

        if (g_frameCount <= 5 || g_frameCount % 60 == 0) {
            char buf[128];
            sprintf_s(buf, sizeof(buf), "Frame %d [Status %d]: RPM=%.1f (target=%d)", 
                      g_frameCount, g_bridge ? g_bridge->status : -1, currentRpm, g_bridge ? g_bridge->targetRpm : 0);
            Log(buf);
        }
    }
}

bool InstallHook() {
    AddVectoredExceptionHandler(1, VectoredHandler);

    BYTE *base = (BYTE *)GetModuleHandleA(NULL);
    if (!base) return false;

    BYTE *callSite = base + 0x11271;
    BYTE *tramp = base + 0xC5720;
    uintptr_t origFunc = (uintptr_t)(base + 0xE610);
    uintptr_t hookLogic = (uintptr_t)DoHookLogic;

    DWORD oldProtect;
    VirtualProtect(tramp, 64, PAGE_EXECUTE_READWRITE, &oldProtect);

    BYTE *p = tramp;
    *p++ = 0x53; // push rbx
    *p++ = 0x48; *p++ = 0x89; *p++ = 0xCB; // mov rbx, rcx
    *p++ = 0x48; *p++ = 0x83; *p++ = 0xEC; *p++ = 0x20; // sub rsp, 20h
    *p++ = 0x48; *p++ = 0xB8;
    *(uintptr_t *)p = origFunc; p += 8; // mov rax, origFunc
    *p++ = 0xFF; *p++ = 0xD0; // call rax
    *p++ = 0x48; *p++ = 0x89; *p++ = 0xD9; // mov rcx, rbx
    *p++ = 0x48; *p++ = 0xB8;
    *(uintptr_t *)p = hookLogic; p += 8; // mov rax, hookLogic
    *p++ = 0xFF; *p++ = 0xD0; // call rax
    *p++ = 0x48; *p++ = 0x83; *p++ = 0xC4; *p++ = 0x20; // add rsp, 20h
    *p++ = 0x5B; // pop rbx
    *p++ = 0xC3; // ret

    VirtualProtect(tramp, 64, oldProtect, &oldProtect);

    VirtualProtect(callSite, 5, PAGE_EXECUTE_READWRITE, &oldProtect);
    int32_t disp = (int32_t)(tramp - (callSite + 5));
    callSite[0] = 0xE8;
    *(int32_t *)(callSite + 1) = disp;
    VirtualProtect(callSite, 5, oldProtect, &oldProtect);

    char buf[128];
    sprintf_s(buf, sizeof(buf), "Hook installed at tramp RVA 0xC5720, bytes=%d, disp=%d", (int)(p - tramp), disp);
    Log(buf);
    return true;
}

BOOL WINAPI DllMain(HINSTANCE hinstDLL, DWORD fdwReason, LPVOID lpvReserved) {
    if (fdwReason == DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls(hinstDLL);
        g_log.open("C:\\Projects\\engine-sim\\engine_hook.log", std::ios::out);
        Log("DLL Attached!");
        InitSharedMemory();
        InstallHook();
    } else if (fdwReason == DLL_PROCESS_DETACH) {
        if (g_bridge != NULL) {
            UnmapViewOfFile(g_bridge);
            g_bridge = NULL;
        }
        if (g_hMapFile != NULL) {
            CloseHandle(g_hMapFile);
            g_hMapFile = NULL;
        }
        if (g_log.is_open()) {
            Log("DLL Detached!");
            g_log.close();
        }
    }
    return TRUE;
}
