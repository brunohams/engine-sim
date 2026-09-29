#include <windows.h>
#include <mmdeviceapi.h>
#include <audioclient.h>
#include <audioclientactivationparams.h>
#include <wrl/implements.h>
#include <wrl/client.h>
#include <iostream>
#include <fstream>
#include <string>
#include <atomic>
#include <thread>
#include <vector>

#pragma comment(lib, "mmdevapi.lib")
#pragma comment(lib, "ole32.lib")

using namespace Microsoft::WRL;

class ActivateCompletionHandler :
    public RuntimeClass<
        RuntimeClassFlags<ClassicCom>,
        FtmBase,
        IActivateAudioInterfaceCompletionHandler>
{
public:
    ActivateCompletionHandler(HANDLE hCompleted)
        : m_hCompleted(hCompleted), m_hr(E_FAIL), m_audioClient(nullptr) {}

    STDMETHODIMP ActivateCompleted(IActivateAudioInterfaceAsyncOperation *operation) override {
        IUnknown *punk = nullptr;
        HRESULT hrResult = S_OK;
        operation->GetActivateResult(&hrResult, &punk);
        m_hr = hrResult;
        if (SUCCEEDED(hrResult) && punk) {
            punk->QueryInterface(IID_PPV_ARGS(&m_audioClient));
            punk->Release();
        }
        SetEvent(m_hCompleted);
        return S_OK;
    }

    HANDLE m_hCompleted;
    HRESULT m_hr;
    IAudioClient *m_audioClient;
};

struct WavHeader {
    char riff[4] = {'R', 'I', 'F', 'F'};
    uint32_t fileSize = 0;
    char wave[4] = {'W', 'A', 'V', 'E'};
    char fmt[4] = {'f', 'm', 't', ' '};
    uint32_t fmtSize = 16;
    uint16_t audioFormat = 1; // PCM
    uint16_t numChannels = 2;
    uint32_t sampleRate = 44100;
    uint32_t byteRate = 44100 * 2 * 2;
    uint16_t blockAlign = 4;
    uint16_t bitsPerSample = 16;
    char data[4] = {'d', 'a', 't', 'a'};
    uint32_t dataSize = 0;
};

int main(int argc, char *argv[]) {
    if (argc < 3) {
        std::cerr << "Usage: process_recorder.exe <PID> <output.wav>" << std::endl;
        return 1;
    }

    DWORD targetPid = std::stoul(argv[1]);
    std::string outputPath = argv[2];

    HRESULT hr = CoInitializeEx(NULL, COINIT_MULTITHREADED);
    if (FAILED(hr)) {
        std::cerr << "CoInitializeEx failed: 0x" << std::hex << hr << std::endl;
        return 1;
    }

    AUDIOCLIENT_ACTIVATION_PARAMS params = {};
    params.ActivationType = AUDIOCLIENT_ACTIVATION_TYPE_PROCESS_LOOPBACK;
    params.ProcessLoopbackParams.TargetProcessId = targetPid;
    params.ProcessLoopbackParams.ProcessLoopbackMode = PROCESS_LOOPBACK_MODE_INCLUDE_TARGET_PROCESS_TREE;

    PROPVARIANT activateParams = {};
    activateParams.vt = VT_BLOB;
    activateParams.blob.cbSize = sizeof(params);
    activateParams.blob.pBlobData = reinterpret_cast<BYTE *>(&params);

    HANDLE hActivateCompleted = CreateEvent(NULL, FALSE, FALSE, NULL);
    ComPtr<ActivateCompletionHandler> handler = Make<ActivateCompletionHandler>(hActivateCompleted);

    ComPtr<IActivateAudioInterfaceAsyncOperation> asyncOp;
    hr = ActivateAudioInterfaceAsync(
        VIRTUAL_AUDIO_DEVICE_PROCESS_LOOPBACK,
        __uuidof(IAudioClient),
        &activateParams,
        handler.Get(),
        &asyncOp
    );

    if (FAILED(hr)) {
        std::cerr << "ActivateAudioInterfaceAsync failed: 0x" << std::hex << hr << std::endl;
        CloseHandle(hActivateCompleted);
        CoUninitialize();
        return 1;
    }

    WaitForSingleObject(hActivateCompleted, INFINITE);
    CloseHandle(hActivateCompleted);

    if (FAILED(handler->m_hr) || !handler->m_audioClient) {
        std::cerr << "Activation completed with error: 0x" << std::hex << handler->m_hr << std::endl;
        CoUninitialize();
        return 1;
    }

    IAudioClient *client = handler->m_audioClient;

    WAVEFORMATEX wfx = {};
    wfx.wFormatTag = WAVE_FORMAT_PCM;
    wfx.nChannels = 2;
    wfx.nSamplesPerSec = 44100;
    wfx.wBitsPerSample = 16;
    wfx.nBlockAlign = wfx.nChannels * (wfx.wBitsPerSample / 8);
    wfx.nAvgBytesPerSec = wfx.nSamplesPerSec * wfx.nBlockAlign;
    wfx.cbSize = 0;

    REFERENCE_TIME hnsBufferDuration = 10000000; // 1s
    DWORD flags = AUDCLNT_STREAMFLAGS_LOOPBACK | AUDCLNT_STREAMFLAGS_EVENTCALLBACK | AUDCLNT_STREAMFLAGS_AUTOCONVERTPCM;
    hr = client->Initialize(AUDCLNT_SHAREMODE_SHARED, flags, hnsBufferDuration, 0, &wfx, nullptr);
    if (FAILED(hr)) {
        std::cerr << "Initialize failed: 0x" << std::hex << hr << std::endl;
        client->Release();
        CoUninitialize();
        return 1;
    }

    HANDLE hAudioEvent = CreateEvent(NULL, FALSE, FALSE, NULL);
    hr = client->SetEventHandle(hAudioEvent);
    if (FAILED(hr)) {
        std::cerr << "SetEventHandle failed: 0x" << std::hex << hr << std::endl;
        client->Release();
        CloseHandle(hAudioEvent);
        CoUninitialize();
        return 1;
    }

    IAudioCaptureClient *captureClient = nullptr;
    hr = client->GetService(IID_PPV_ARGS(&captureClient));
    if (FAILED(hr)) {
        std::cerr << "GetService(IAudioCaptureClient) failed: 0x" << std::hex << hr << std::endl;
        client->Release();
        CloseHandle(hAudioEvent);
        CoUninitialize();
        return 1;
    }

    std::ofstream wavFile(outputPath, std::ios::binary);
    if (!wavFile.is_open()) {
        std::cerr << "Failed to open output file: " << outputPath << std::endl;
        captureClient->Release();
        client->Release();
        CloseHandle(hAudioEvent);
        CoUninitialize();
        return 1;
    }

    WavHeader header;
    wavFile.write(reinterpret_cast<const char *>(&header), sizeof(header));

    double recordDuration = -1.0;
    if (argc >= 4) {
        recordDuration = std::stod(argv[3]);
    }

    std::atomic<bool> isRunning(true);
    std::thread inputThread([&isRunning, recordDuration]() {
        if (recordDuration > 0) {
            std::this_thread::sleep_for(std::chrono::milliseconds(static_cast<int>(recordDuration * 1000)));
            isRunning = false;
        } else {
            std::string line;
            std::getline(std::cin, line);
            isRunning = false;
        }
    });

    hr = client->Start();
    if (FAILED(hr)) {
        std::cerr << "Start failed: 0x" << std::hex << hr << std::endl;
        isRunning = false;
    } else {
        std::cout << "RECORDING_STARTED" << std::endl;
    }

    uint32_t totalDataBytes = 0;
    std::vector<BYTE> zeroBuffer;

    while (isRunning.load()) {
        DWORD waitResult = WaitForSingleObject(hAudioEvent, 50);
        if (waitResult == WAIT_OBJECT_0) {
            UINT32 packetLength = 0;
            hr = captureClient->GetNextPacketSize(&packetLength);
            while (packetLength > 0 && SUCCEEDED(hr)) {
                BYTE *pData = nullptr;
                UINT32 numFramesAvailable = 0;
                DWORD bufferFlags = 0;
                hr = captureClient->GetBuffer(&pData, &numFramesAvailable, &bufferFlags, nullptr, nullptr);
                if (SUCCEEDED(hr)) {
                    size_t bytes = numFramesAvailable * wfx.nBlockAlign;
                    if (bufferFlags & AUDCLNT_BUFFERFLAGS_SILENT) {
                        if (zeroBuffer.size() < bytes) zeroBuffer.resize(bytes, 0);
                        wavFile.write(reinterpret_cast<const char *>(zeroBuffer.data()), bytes);
                    } else {
                        wavFile.write(reinterpret_cast<const char *>(pData), bytes);
                    }
                    totalDataBytes += static_cast<uint32_t>(bytes);
                    captureClient->ReleaseBuffer(numFramesAvailable);
                }
                hr = captureClient->GetNextPacketSize(&packetLength);
            }
        }
    }

    client->Stop();

    // Finalize WAV Header
    header.dataSize = totalDataBytes;
    header.fileSize = totalDataBytes + sizeof(WavHeader) - 8;
    wavFile.seekp(0, std::ios::beg);
    wavFile.write(reinterpret_cast<const char *>(&header), sizeof(header));
    wavFile.close();

    std::cout << "RECORDING_FINISHED " << totalDataBytes << std::endl;

    if (inputThread.joinable()) {
        inputThread.detach();
    }

    captureClient->Release();
    client->Release();
    CloseHandle(hAudioEvent);
    CoUninitialize();

    return 0;
}
