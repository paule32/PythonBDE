// PythonBDE Crash Watchdog, Windows GUI subsystem, MinGW32/MinGW64.
// This program is a separate process. It deliberately never loads Python or Qt.
#define WIN32_LEAN_AND_MEAN
#define NOMINMAX
#ifndef _WIN32_WINNT
#define _WIN32_WINNT 0x0601
#endif
#include <windows.h>
#include <shellapi.h>
#include <string>
#include <vector>
#include <sstream>
#include <iomanip>
#include <algorithm>
#include <cwchar>
#include <cstdlib>
#include <cstring>
#include <initializer_list>
#include <utility>

namespace {
constexpr int ID_TRACE = 1001;
constexpr int ID_COPY = 1002;
constexpr int ID_CLOSE = 1003;
constexpr DWORD MAX_LOG_BYTES = 48 * 1024;

struct Options {
    DWORD pid = 0;
    std::wstring role = L"PythonBDE";
    std::wstring fatalLog;
    std::wstring errorLog;
    std::wstring readyEvent;
};

struct DialogState {
    std::wstring title;
    std::wstring details;
    HWND editor = nullptr;
    HWND copy = nullptr;
    HWND close = nullptr;
};

std::wstring utf8_to_wide(const char* ptr, int n) {
    if (!ptr || n <= 0) return L"";
    int count = MultiByteToWideChar(CP_UTF8, 0, ptr, n, nullptr, 0);
    if (count <= 0) return L"";
    std::wstring value(static_cast<size_t>(count), L'\0');
    MultiByteToWideChar(CP_UTF8, 0, ptr, n, &value[0], count);
    return value;
}

std::wstring windows_lines(const std::wstring& value) {
    std::wstring out;
    out.reserve(value.size() + value.size() / 10);
    for (size_t i = 0; i < value.size(); ++i) {
        if (value[i] == L'\n' && (i == 0 || value[i - 1] != L'\r')) out += L'\r';
        out += value[i];
    }
    return out;
}

std::wstring read_tail(const std::wstring& file) {
    if (file.empty()) return L"";
    HANDLE h = CreateFileW(file.c_str(), GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE | FILE_SHARE_DELETE,
                            nullptr, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
    if (h == INVALID_HANDLE_VALUE) return L"";
    LARGE_INTEGER length{};
    if (!GetFileSizeEx(h, &length) || length.QuadPart < 1) {
        CloseHandle(h);
        return L"";
    }
    const DWORD size = static_cast<DWORD>(std::min<LONGLONG>(length.QuadPart, MAX_LOG_BYTES));
    LARGE_INTEGER offset{};
    offset.QuadPart = length.QuadPart - size;
    if (!SetFilePointerEx(h, offset, nullptr, FILE_BEGIN)) {
        CloseHandle(h);
        return L"";
    }
    std::vector<char> bytes(size);
    DWORD read = 0;
    const BOOL ok = ReadFile(h, bytes.data(), size, &read, nullptr);
    CloseHandle(h);
    if (!ok) return L"";
    return windows_lines(utf8_to_wide(bytes.data(), static_cast<int>(read)));
}

std::wstring status_hex(DWORD code) {
    std::wostringstream out;
    out << L"0x" << std::uppercase << std::hex << std::setfill(L'0') << std::setw(8) << code;
    return out.str();
}

bool parse_args(Options& opt) {
    int argc = 0;
    LPWSTR* argv = CommandLineToArgvW(GetCommandLineW(), &argc);
    if (!argv) return false;
    for (int i = 1; i + 1 < argc; i += 2) {
        const std::wstring name = argv[i];
        const std::wstring value = argv[i + 1];
        if (name == L"--pid") {
            wchar_t* end = nullptr;
            const unsigned long number = wcstoul(value.c_str(), &end, 10);
            if (!end || *end || number == 0) { LocalFree(argv); return false; }
            opt.pid = static_cast<DWORD>(number);
        } else if (name == L"--role") opt.role = value;
        else if (name == L"--fatal-log") opt.fatalLog = value;
        else if (name == L"--error-log") opt.errorLog = value;
        else if (name == L"--ready-event") opt.readyEvent = value;
        else { LocalFree(argv); return false; }
    }
    const bool valid = argc >= 3 && (argc % 2 == 1) && opt.pid != 0;
    LocalFree(argv);
    return valid;
}

void notify_ready(const std::wstring& name) {
    if (name.empty()) return;
    HANDLE event = OpenEventW(EVENT_MODIFY_STATE, FALSE, name.c_str());
    if (event) {
        SetEvent(event);
        CloseHandle(event);
    }
}

void copy_to_clipboard(HWND hwnd, const std::wstring& text) {
    if (!OpenClipboard(hwnd)) return;
    if (EmptyClipboard()) {
        const SIZE_T bytes = (text.size() + 1) * sizeof(wchar_t);
        HGLOBAL memory = GlobalAlloc(GMEM_MOVEABLE, bytes);
        if (memory) {
            wchar_t* buffer = static_cast<wchar_t*>(GlobalLock(memory));
            if (buffer) {
                memcpy(buffer, text.c_str(), bytes);
                GlobalUnlock(memory);
                if (SetClipboardData(CF_UNICODETEXT, memory)) memory = nullptr;
            }
            if (memory) GlobalFree(memory);
        }
    }
    CloseClipboard();
}

void layout(HWND hwnd, DialogState* state) {
    if (!state) return;
    RECT rc{};
    GetClientRect(hwnd, &rc);
    // RECT coordinates use Win32 LONG. std::max requires identical argument types.
    // Cast the difference explicitly for MinGW-w32 and MinGW-w64 (GCC 16+).
    const int w = std::max(100, static_cast<int>(rc.right - rc.left));
    const int h = std::max(100, static_cast<int>(rc.bottom - rc.top));
    if (state->editor) MoveWindow(state->editor, 12, 12, w - 24, std::max(20, h - 68), TRUE);
    if (state->copy) MoveWindow(state->copy, std::max(12, w - 266), h - 44, 140, 30, TRUE);
    if (state->close) MoveWindow(state->close, std::max(155, w - 116), h - 44, 104, 30, TRUE);
}

LRESULT CALLBACK window_proc(HWND hwnd, UINT msg, WPARAM wp, LPARAM lp) {
    auto* state = reinterpret_cast<DialogState*>(GetWindowLongPtrW(hwnd, GWLP_USERDATA));
    switch (msg) {
    case WM_NCCREATE: {
        auto* cs = reinterpret_cast<CREATESTRUCTW*>(lp);
        SetWindowLongPtrW(hwnd, GWLP_USERDATA, reinterpret_cast<LONG_PTR>(cs->lpCreateParams));
        return TRUE;
    }
    case WM_CREATE: {
        state = reinterpret_cast<DialogState*>(GetWindowLongPtrW(hwnd, GWLP_USERDATA));
        if (!state) return -1;
        state->editor = CreateWindowExW(WS_EX_CLIENTEDGE, L"EDIT", state->details.c_str(),
            WS_CHILD | WS_VISIBLE | WS_VSCROLL | WS_HSCROLL | ES_MULTILINE | ES_READONLY |
            ES_AUTOVSCROLL | ES_AUTOHSCROLL, 0, 0, 100, 100, hwnd,
            reinterpret_cast<HMENU>(static_cast<INT_PTR>(ID_TRACE)), GetModuleHandleW(nullptr), nullptr);
        state->copy = CreateWindowExW(0, L"BUTTON", L"Copy Traceback", WS_CHILD | WS_VISIBLE | BS_PUSHBUTTON,
            0, 0, 100, 25, hwnd, reinterpret_cast<HMENU>(static_cast<INT_PTR>(ID_COPY)),
            GetModuleHandleW(nullptr), nullptr);
        state->close = CreateWindowExW(0, L"BUTTON", L"Close", WS_CHILD | WS_VISIBLE | BS_DEFPUSHBUTTON,
            0, 0, 100, 25, hwnd, reinterpret_cast<HMENU>(static_cast<INT_PTR>(ID_CLOSE)),
            GetModuleHandleW(nullptr), nullptr);
        if (!state->editor || !state->copy || !state->close) return -1;
        HFONT font = static_cast<HFONT>(GetStockObject(DEFAULT_GUI_FONT));
        for (HWND child : {state->editor, state->copy, state->close})
            SendMessageW(child, WM_SETFONT, reinterpret_cast<WPARAM>(font), TRUE);
        layout(hwnd, state);
        return 0;
    }
    case WM_SIZE:
        layout(hwnd, state);
        return 0;
    case WM_COMMAND:
        if (LOWORD(wp) == ID_COPY && state) { copy_to_clipboard(hwnd, state->details); return 0; }
        if (LOWORD(wp) == ID_CLOSE) { DestroyWindow(hwnd); return 0; }
        break;
    case WM_CLOSE:
        DestroyWindow(hwnd);
        return 0;
    case WM_DESTROY:
        PostQuitMessage(0);
        return 0;
    }
    return DefWindowProcW(hwnd, msg, wp, lp);
}

void show_crash(DialogState& state) {
    const HINSTANCE instance = GetModuleHandleW(nullptr);
    WNDCLASSEXW wc{};
    wc.cbSize = sizeof(wc);
    wc.lpfnWndProc = window_proc;
    wc.hInstance = instance;
    wc.hCursor = LoadCursorW(nullptr, IDC_ARROW);
    wc.hIcon = LoadIconW(nullptr, IDI_ERROR);
    wc.hbrBackground = reinterpret_cast<HBRUSH>(COLOR_BTNFACE + 1);
    wc.lpszClassName = L"PythonBDECrashWatchdogDialog";
    RegisterClassExW(&wc);
    HWND wnd = CreateWindowExW(WS_EX_APPWINDOW, wc.lpszClassName, state.title.c_str(),
        WS_OVERLAPPEDWINDOW | WS_VISIBLE, CW_USEDEFAULT, CW_USEDEFAULT, 900, 600,
        nullptr, nullptr, instance, &state);
    if (!wnd) {
        MessageBoxW(nullptr, state.details.substr(0, 2800).c_str(), state.title.c_str(),
                    MB_OK | MB_ICONERROR | MB_SYSTEMMODAL);
        return;
    }
    ShowWindow(wnd, SW_SHOW);
    UpdateWindow(wnd);
    MSG msg{};
    while (GetMessageW(&msg, nullptr, 0, 0) > 0) {
        TranslateMessage(&msg);
        DispatchMessageW(&msg);
    }
}

} // namespace

int WINAPI wWinMain(HINSTANCE, HINSTANCE, PWSTR, int) {
    Options opt;
    if (!parse_args(opt)) return 2;

    // A PID-scoped named mutex ensures that a second launcher cannot create a
    // second watcher for the same running process. Different sessions are distinct.
    const std::wstring mutexName = L"Local\\PythonBDE_Watchdog_" + std::to_wstring(opt.pid);
    HANDLE mutex = CreateMutexW(nullptr, TRUE, mutexName.c_str());
    if (!mutex) return 3;
    if (GetLastError() == ERROR_ALREADY_EXISTS) {
        CloseHandle(mutex);
        notify_ready(opt.readyEvent);
        return 0;
    }

    HANDLE process = OpenProcess(SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION, FALSE, opt.pid);
    if (!process) {
        ReleaseMutex(mutex);
        CloseHandle(mutex);
        return 4;
    }
    notify_ready(opt.readyEvent);
    const DWORD wait = WaitForSingleObject(process, INFINITE);
    DWORD code = 0;
    const bool valid = wait == WAIT_OBJECT_0 && GetExitCodeProcess(process, &code);
    CloseHandle(process);
    ReleaseMutex(mutex);
    CloseHandle(mutex);
    if (!valid || code == 0) return valid ? 0 : 5;

    const std::wstring fatal = read_tail(opt.fatalLog);
    // 1/2 are used by PythonBDE for intentionally cancelled startup/login,
    // so they are only shown if a native fatal traceback was actually written.
    if ((code == 1 || code == 2) && fatal.empty()) return 0;

    std::wstring text = L"The monitored PythonBDE process terminated unexpectedly.\r\n";
    text += L"Application: " + opt.role + L"\r\n";
    text += L"Process ID: " + std::to_wstring(opt.pid) + L"\r\n";
    text += L"Exit code: " + status_hex(code) + L" (" + std::to_wstring(code) + L")\r\n";
    text += L"\r\n";
    if (!fatal.empty()) text += L"=== Native / faulthandler traceback ===\r\n" + fatal + L"\r\n\r\n";
    const std::wstring ordinary = read_tail(opt.errorLog);
    if (!ordinary.empty()) text += L"=== Last PythonBDE error log entries ===\r\n" + ordinary + L"\r\n";
    if (fatal.empty() && ordinary.empty()) text += L"No traceback was recorded. Check Windows Event Viewer / WER LocalDumps.\r\n";

    DialogState state;
    state.title = opt.role + L" - Crash Watchdog";
    state.details = std::move(text);
    show_crash(state);
    return 0;
}
