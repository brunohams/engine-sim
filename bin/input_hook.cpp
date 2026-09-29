#include <windows.h>
#include <stdio.h>

typedef UINT (WINAPI *pfnGetRawInputData)(HRAWINPUT hRawInput, UINT uiCommand, LPVOID pData, PUINT pcbSize, UINT cbSizeHeader);
static pfnGetRawInputData g_originalGetRawInputData = nullptr;
static HANDLE g_fakeKeyboard = (HANDLE)0xFEED0001;

void LogMessage(const char *msg) {
    HANDLE hFile = CreateFileA("C:\\Projects\\engine-sim\\hook_debug.log", 
                               FILE_APPEND_DATA, FILE_SHARE_READ, NULL, 
                               OPEN_ALWAYS, FILE_ATTRIBUTE_NORMAL, NULL);
    if (hFile != INVALID_HANDLE_VALUE) {
        DWORD written;
        WriteFile(hFile, msg, (DWORD)strlen(msg), &written, NULL);
        CloseHandle(hFile);
    }
}

UINT WINAPI HookGetRawInputData(HRAWINPUT hRawInput, UINT uiCommand, LPVOID pData, PUINT pcbSize, UINT cbSizeHeader) {
    UINT result = g_originalGetRawInputData(hRawInput, uiCommand, pData, pcbSize, cbSizeHeader);
    if (result != (UINT)-1 && pData != NULL && uiCommand == RID_INPUT) {
        RAWINPUT *raw = (RAWINPUT *)pData;
        char buf[128];
        sprintf_s(buf, sizeof(buf), "GetRawInputData: type=%u hDevice=%p\n", raw->header.dwType, raw->header.hDevice);
        LogMessage(buf);

        if (raw->header.dwType == RIM_TYPEKEYBOARD) {
            sprintf_s(buf, sizeof(buf), "  -> Keyboard: VKey=0x%X Flags=0x%X prev_hDevice=%p\n", 
                      raw->data.keyboard.VKey, raw->data.keyboard.Flags, raw->header.hDevice);
            LogMessage(buf);
            if (raw->header.hDevice == NULL) {
                raw->header.hDevice = g_fakeKeyboard;
                LogMessage("  -> Patched hDevice to fake keyboard!\n");
            }
        }
    }
    return result;
}

DWORD WINAPI BackgroundSetupThread(LPVOID lpParam) {
    BYTE *base = (BYTE *)GetModuleHandleA(NULL);
    if (!base) return 0;

    LogMessage("BackgroundSetupThread started...\n");
    // Wait for ysWindowSystem::g_instance at 0x102480
    void **pGInstance = (void **)(base + 0x102480);
    for (int i = 0; i < 50; i++) {
        if (*pGInstance != nullptr) break;
        Sleep(100);
    }

    if (*pGInstance == nullptr) {
        LogMessage("Timed out waiting for g_instance!\n");
        return 0;
    }

    BYTE *g_instance = (BYTE *)(*pGInstance);
    void **pInputSystem = (void **)(g_instance + 0x40);
    for (int i = 0; i < 50; i++) {
        if (*pInputSystem != nullptr) break;
        Sleep(100);
    }

    if (*pInputSystem == nullptr) {
        LogMessage("Timed out waiting for inputSystem!\n");
        return 0;
    }

    BYTE *inputSystem = (BYTE *)(*pInputSystem);
    // m_enableGlobalInput is at offset 0x1C8
    BYTE *pEnableGlobal = inputSystem + 0x1C8;
    *pEnableGlobal = 1;
    LogMessage("m_enableGlobalInput set to 1 successfully!\n");
    return 0;
}

bool InstallHook() {
    BYTE *base = (BYTE *)GetModuleHandleA(NULL);
    if (!base) return false;

    void **pSlot = (void **)(base + 0xC6618);
    g_originalGetRawInputData = (pfnGetRawInputData)*pSlot;

    DWORD oldProtect;
    if (!VirtualProtect(pSlot, sizeof(void*), PAGE_READWRITE, &oldProtect)) {
        LogMessage("VirtualProtect failed!\n");
        return false;
    }

    *pSlot = (void *)HookGetRawInputData;
    VirtualProtect(pSlot, sizeof(void*), oldProtect, &oldProtect);

    LogMessage("Hook installed successfully at RVA 0xC6618!\n");
    CreateThread(NULL, 0, BackgroundSetupThread, NULL, 0, NULL);
    return true;
}

BOOL WINAPI DllMain(HINSTANCE hinstDLL, DWORD fdwReason, LPVOID lpvReserved) {
    if (fdwReason == DLL_PROCESS_ATTACH) {
        DisableThreadLibraryCalls(hinstDLL);
        LogMessage("DLL_PROCESS_ATTACH\n");
        InstallHook();
    }
    return TRUE;
}
