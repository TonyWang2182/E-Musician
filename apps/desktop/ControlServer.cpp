#include "ControlServer.h"
#include "EngineSession.h"
#include <juce_events/juce_events.h>
#include <atomic>
#include <chrono>
#include <condition_variable>
#include <cstdint>
#include <cstdio>
#include <deque>
#include <iostream>
#include <limits>
#include <mutex>
#include <set>
#include <string>
#include <stdexcept>
#include <thread>
#include <utility>

#if JUCE_WINDOWS
 #ifndef NOMINMAX
  #define NOMINMAX
 #endif
 #ifndef WIN32_LEAN_AND_MEAN
  #define WIN32_LEAN_AND_MEAN
 #endif
 #include <windows.h>
 #include <fcntl.h>
 #include <io.h>
#endif

namespace emusician {
namespace {
constexpr std::size_t maximumLineBytes = 1024 * 1024;
constexpr std::size_t maximumQueuedFrames = 32;

#if JUCE_WINDOWS
struct NativeHandle {
    HANDLE value = nullptr;
    NativeHandle() = default;
    explicit NativeHandle(HANDLE h) : value(h) {}
    NativeHandle(const NativeHandle&) = delete;
    NativeHandle& operator=(const NativeHandle&) = delete;
    NativeHandle(NativeHandle&& other) noexcept : value(std::exchange(other.value, nullptr)) {}
    NativeHandle& operator=(NativeHandle&& other) noexcept
    { if (this != &other) { reset(); value = std::exchange(other.value, nullptr); } return *this; }
    ~NativeHandle() { reset(); }
    void reset() { if (value && value != INVALID_HANDLE_VALUE) CloseHandle(value); value = nullptr; }
    HANDLE release() { return std::exchange(value, nullptr); }
};
NativeHandle duplicateHandle(HANDLE original, bool inherited)
{
    HANDLE copy = nullptr;
    if (!original || original == INVALID_HANDLE_VALUE
        || !DuplicateHandle(GetCurrentProcess(), original, GetCurrentProcess(), &copy, 0,
                            inherited ? TRUE : FALSE, DUPLICATE_SAME_ACCESS))
        throw std::runtime_error("Cannot duplicate the control stream handle.");
    return NativeHandle(copy);
}
void bindCrtStdout(HANDLE diagnostics)
{
    // In a Windows GUI process _fileno(stdout) may be -2. Reopen the FILE first
    // rather than passing that sentinel to _dup2 or the CRT invalid handler.
    // The private protocol handle has already been duplicated before this call.
    std::fflush(stdout);
    FILE* rebound = nullptr;
    if (freopen_s(&rebound, "NUL", "w", stdout) != 0 || !rebound || _fileno(stdout) < 0)
        throw std::runtime_error("Cannot initialise diagnostic stdout.");
    auto owned = duplicateHandle(diagnostics, false);
    const int descriptor = _open_osfhandle(reinterpret_cast<intptr_t>(owned.value), _O_WRONLY | _O_TEXT);
    if (descriptor < 0) throw std::runtime_error("Cannot open diagnostic stdout descriptor.");
    owned.release(); // The CRT descriptor owns this duplicate from now on.
    const int output = _fileno(stdout);
    const bool bound = _dup2(descriptor, output) == 0 && (output == 1 || _dup2(descriptor, 1) == 0);
    if (descriptor != output && descriptor != 1) _close(descriptor);
    if (!bound) throw std::runtime_error("Cannot redirect diagnostic stdout.");
    std::setvbuf(stdout, nullptr, _IONBF, 0);
    std::cout.clear();
    // CRT operations can update the Win32 standard handle, so set it last.
    if (!SetStdHandle(STD_OUTPUT_HANDLE, diagnostics))
        throw std::runtime_error("Cannot redirect the Win32 diagnostic stdout handle.");
}
bool emitOutputProbe(const char* scope)
{
    const auto prefix = std::string("CONTROL_OUTPUT_PROBE_") + scope + "_";
    bool ok = std::printf("%sPRINTF\n", prefix.c_str()) > 0 && std::fflush(stdout) == 0;
    std::cout << prefix << "COUT\n" << std::flush;
    ok = std::cout.good() && ok;
    const auto crt = prefix + "CRT\n";
    ok = _write(1, crt.data(), static_cast<unsigned int>(crt.size())) == static_cast<int>(crt.size()) && ok;
    const auto native = prefix + "WIN32\n";
    DWORD written = 0;
    ok = WriteFile(GetStdHandle(STD_OUTPUT_HANDLE), native.data(), static_cast<DWORD>(native.size()), &written, nullptr)
        && written == native.size() && ok;
    return ok;
}
#endif

juce::var protocolError(const juce::String& code, const juce::String& message)
{
    auto error = std::make_unique<juce::DynamicObject>();
    error->setProperty("code", code); error->setProperty("message", message);
    auto result = std::make_unique<juce::DynamicObject>();
    result->setProperty("ok", false); result->setProperty("status", "failed");
    result->setProperty("error", juce::var(error.release()));
    return juce::var(result.release());
}

// Guard known permissive/overflow paths in the pinned JUCE JSON parser before
// passing a bounded envelope to it. Duplicate keys and trailing data are errors.
juce::Result parseEnvelope(const std::string& text, juce::var& envelope)
{
    using juce::String;
    using juce::Result;
    using juce::var;
    if (text.empty() || text.size() > maximumLineBytes
        || !juce::CharPointer_UTF8::isValidString(text.data(), static_cast<int>(text.size())))
        return Result::fail("A request must be a non-empty UTF-8 JSON object of at most 1 MiB.");
    struct Level { char kind; std::set<String> keys; };
    std::vector<Level> levels;
    bool finished = false;
    char previous = 0;
    const auto space = [](char c) { return c == ' ' || c == '\t' || c == '\r'; };
    const auto digit = [](char c) { return c >= '0' && c <= '9'; };
    for (std::size_t i = 0; i < text.size();) {
        const char c = text[i];
        if (space(c)) { ++i; continue; }
        if (c == 0 || finished) return Result::fail("Trailing or null data is not allowed.");
        if (levels.empty() && c != '{') return Result::fail("A request must contain one JSON object.");
        if (c == '"') {
            const auto start = i++;
            bool closed = false;
            while (i < text.size()) {
                const auto ch = static_cast<unsigned char>(text[i++]);
                if (ch < 0x20) return Result::fail("Invalid control character in JSON string.");
                if (ch == '\\') {
                    if (i >= text.size() || static_cast<unsigned char>(text[i]) < 0x20)
                        return Result::fail("Invalid JSON string escape.");
                    ++i;
                } else if (ch == '"') { closed = true; break; }
            }
            if (!closed) return Result::fail("Unfinished JSON string.");
            auto next = i;
            while (next < text.size() && space(text[next])) ++next;
            if (next < text.size() && text[next] == ':') {
                if (levels.back().kind != '{') return Result::fail("JSON property outside an object.");
                const auto quoted = String::fromUTF8(text.data() + start, static_cast<int>(i - start));
                auto cursor = quoted.getCharPointer();
                var key;
                if (auto result = juce::JSON::parseQuotedString(cursor, key); result.failed()) return result;
                if (!levels.back().keys.insert(key.toString()).second)
                    return Result::fail("Duplicate JSON property: " + key.toString());
            }
            previous = '"';
            continue;
        }
        if (c == '{' || c == '[') {
            if (levels.size() >= 32) return Result::fail("JSON request nesting exceeds 32 levels.");
            levels.push_back({ c, {} }); previous = c; ++i; continue;
        }
        if (c == '}' || c == ']') {
            if (levels.empty() || levels.back().kind != (c == '}' ? '{' : '[') || previous == ',')
                return Result::fail("Invalid JSON object or array boundary.");
            levels.pop_back(); finished = levels.empty(); previous = c; ++i; continue;
        }
        if (c == '-' || digit(c)) {
            if (c == '-') ++i;
            if (i >= text.size() || !digit(text[i])) return Result::fail("Invalid JSON number.");
            const auto first = i;
            std::uint64_t value = 0;
            constexpr auto limit = static_cast<std::uint64_t>(std::numeric_limits<juce::int64>::max());
            while (i < text.size() && digit(text[i])) {
                const auto next = static_cast<std::uint64_t>(text[i] - '0');
                if (value > (limit - next) / 10) return Result::fail("JSON integer exceeds signed 64-bit range.");
                value = value * 10 + next; ++i;
            }
            if (i - first > 1 && text[first] == '0') return Result::fail("Leading zero in JSON number.");
            if (i < text.size() && text[i] == '.') {
                ++i;
                if (i >= text.size() || !digit(text[i])) return Result::fail("Invalid JSON decimal.");
                while (i < text.size() && digit(text[i])) ++i;
            }
            if (i < text.size() && (text[i] == 'e' || text[i] == 'E')) {
                ++i;
                if (i < text.size() && (text[i] == '+' || text[i] == '-')) ++i;
                if (i >= text.size() || !digit(text[i])) return Result::fail("Invalid JSON exponent.");
                int exponent = 0;
                while (i < text.size() && digit(text[i])) {
                    const int next = text[i++] - '0';
                    if (exponent > (1000000 - next) / 10) return Result::fail("JSON exponent exceeds parser range.");
                    exponent = exponent * 10 + next;
                }
            }
            if (i < text.size() && !space(text[i]) && text[i] != ',' && text[i] != '}' && text[i] != ']')
                return Result::fail("Invalid JSON number boundary.");
            previous = '0';
            continue;
        }
        previous = c; ++i;
    }
    if (!finished) return Result::fail("Incomplete JSON object.");
    return juce::JSON::parse(String::fromUTF8(text.data(), static_cast<int>(text.size())), envelope);
}
}

struct ControlStdio::Impl {
#if JUCE_WINDOWS
    NativeHandle protocol, diagnostics;
    Impl()
    {
        const auto original = GetStdHandle(STD_OUTPUT_HANDLE);
        const auto type = original && original != INVALID_HANDLE_VALUE ? GetFileType(original) : FILE_TYPE_UNKNOWN;
        if (type != FILE_TYPE_PIPE && type != FILE_TYPE_DISK)
            throw std::runtime_error("Control stdout must be a redirected pipe or file.");
        protocol = duplicateHandle(original, false);
        // With an uninitialised GUI CRT, reopening stdout may leave the old
        // Win32 handle open. It must not leak the protocol pipe to children.
        if (!SetHandleInformation(original, HANDLE_FLAG_INHERIT, 0))
            throw std::runtime_error("Cannot prevent protocol stdout inheritance.");
        const auto error = GetStdHandle(STD_ERROR_HANDLE);
        if (error && error != INVALID_HANDLE_VALUE && GetFileType(error) != FILE_TYPE_UNKNOWN)
            diagnostics = duplicateHandle(error, true);
        else {
            SECURITY_ATTRIBUTES security { sizeof(SECURITY_ATTRIBUTES), nullptr, TRUE };
            diagnostics = NativeHandle(CreateFileW(L"NUL", GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE,
                                                    &security, OPEN_EXISTING, 0, nullptr));
            if (diagnostics.value == INVALID_HANDLE_VALUE)
                throw std::runtime_error("Cannot create a diagnostic output sink.");
        }
        bindCrtStdout(diagnostics.value);
    }
    ~Impl()
    {
        // Never reconnect ordinary stdout to the protocol pipe. CRT stdout has
        // its own diagnostic duplicate; late runtime destructors keep that sink.
        const auto error = GetStdHandle(STD_ERROR_HANDLE);
        SetStdHandle(STD_OUTPUT_HANDLE, error == diagnostics.value ? nullptr : error);
    }
#else
    Impl() { throw std::runtime_error("The local control transport is implemented for Windows."); }
#endif
};
ControlStdio::ControlStdio() : impl(std::make_unique<Impl>()) {}
ControlStdio::~ControlStdio() = default;
juce::Result ControlStdio::runOutputProbe() const
{
#if JUCE_WINDOWS
    DWORD flags = 0;
    if (!GetHandleInformation(impl->protocol.value, &flags) || (flags & HANDLE_FLAG_INHERIT) != 0)
        return juce::Result::fail("Private protocol handle must not be inherited.");
    if (!emitOutputProbe("PARENT")) return juce::Result::fail("Parent diagnostic output probe failed.");
    const char nonInherited[] = "CONTROL_OUTPUT_PROBE_PROTOCOL_NONINHERIT\n";
    DWORD written = 0;
    if (!WriteFile(impl->diagnostics.value, nonInherited, sizeof(nonInherited) - 1, &written, nullptr)
        || written != sizeof(nonInherited) - 1) return juce::Result::fail("Cannot write probe status.");
    const auto executable = juce::File::getSpecialLocation(juce::File::currentExecutableFile).getFullPathName();
    std::wstring command((executable.quoted() + " --control-output-probe-child").toWideCharPointer());
    auto input = duplicateHandle(GetStdHandle(STD_INPUT_HANDLE), true);
    STARTUPINFOW startup{}; startup.cb = sizeof(startup); startup.dwFlags = STARTF_USESTDHANDLES;
    startup.hStdInput = input.value; startup.hStdOutput = startup.hStdError = impl->diagnostics.value;
    PROCESS_INFORMATION process{};
    if (!CreateProcessW(executable.toWideCharPointer(), command.data(), nullptr, nullptr, TRUE,
                        CREATE_NO_WINDOW, nullptr, nullptr, &startup, &process))
        return juce::Result::fail("Cannot start inherited-stdout probe child.");
    NativeHandle ownedProcess(process.hProcess), ownedThread(process.hThread);
    if (WaitForSingleObject(ownedProcess.value, 5000) != WAIT_OBJECT_0) {
        TerminateProcess(ownedProcess.value, 2); WaitForSingleObject(ownedProcess.value, 1000);
        return juce::Result::fail("Inherited-stdout probe child timed out.");
    }
    DWORD code = 1;
    if (!GetExitCodeProcess(ownedProcess.value, &code) || code != 0)
        return juce::Result::fail("Inherited-stdout probe child failed.");
    return juce::Result::ok();
#else
    return juce::Result::fail("The output probe is implemented for Windows.");
#endif
}
int ControlStdio::runOutputProbeChild()
{
#if JUCE_WINDOWS
    try {
        // A GUI child may also start with an uninitialised CRT stdout. Keep its
        // inherited Win32 sink alive while initialising the CRT streams.
        auto inherited = duplicateHandle(GetStdHandle(STD_OUTPUT_HANDLE), false);
        bindCrtStdout(inherited.value);
        return emitOutputProbe("CHILD") ? 0 : 2;
    } catch (...) { return 2; }
#else
    return 2;
#endif
}

struct ControlServer::Impl final : private juce::AsyncUpdater, private juce::Timer {
    struct Frame { std::string text; bool oversized = false; };
    EngineSession& session;
    void* protocolOutput = nullptr;
    std::function<void()> onQuit;
    std::mutex mutex;
    std::condition_variable changed;
    std::deque<Frame> requests;
    std::deque<std::string> replies;
    std::atomic<bool> stopping { false }, readerEnded { false }, outputFailed { false };
    bool writing = false, quitNotified = false;
    std::thread reader, writer;

    Impl(EngineSession& value, void* output, std::function<void()> quit)
        : session(value), protocolOutput(output), onQuit(std::move(quit))
    {
        jassert(juce::MessageManager::getInstance()->isThisTheMessageThread());
        startTimerHz(20);
        try {
            reader = std::thread([this] { readLoop(); });
            writer = std::thread([this] { writeLoop(); });
        } catch (...) {
            stopWorkers();
            throw;
        }
    }
    ~Impl() override
    {
        stopWorkers();
    }
    void stopWorkers()
    {
        stopTimer(); stopping = true;
        changed.notify_all(); cancelPendingUpdate();
        const auto join = [](std::thread& thread) {
            if (!thread.joinable()) return;
       #if JUCE_WINDOWS
            const auto handle = static_cast<HANDLE>(thread.native_handle());
            // Cancellation can race the start of WriteFile. Repeat until exit,
            // instead of cancelling once and joining a newly blocked write.
            do { CancelSynchronousIo(handle); }
            while (WaitForSingleObject(handle, 10) == WAIT_TIMEOUT);
       #endif
            thread.join();
        };
        join(reader); join(writer);
        cancelPendingUpdate();
    }
    bool enqueue(Frame frame)
    {
        std::unique_lock lock(mutex);
        changed.wait(lock, [this] { return stopping || requests.size() < maximumQueuedFrames; });
        if (stopping) return false;
        requests.push_back(std::move(frame));
        lock.unlock(); triggerAsyncUpdate();
        return true;
    }
    void readLoop()
    {
       #if JUCE_WINDOWS
        const auto input = GetStdHandle(STD_INPUT_HANDLE);
        const auto type = input == nullptr || input == INVALID_HANDLE_VALUE ? FILE_TYPE_UNKNOWN : GetFileType(input);
        if (type != FILE_TYPE_PIPE && type != FILE_TYPE_DISK) {
            std::cerr << "Control stdin must be a redirected pipe or file.\n";
            readerEnded = true; triggerAsyncUpdate(); return;
        }
        std::string line;
        line.reserve(4096);
        bool oversized = false;
        char buffer[4096];
        while (!stopping) {
            DWORD available = sizeof(buffer);
            if (type == FILE_TYPE_PIPE) {
                if (!PeekNamedPipe(input, nullptr, 0, nullptr, &available, nullptr)) break;
                if (available == 0) {
                    std::unique_lock lock(mutex);
                    changed.wait_for(lock, std::chrono::milliseconds(10), [this] { return stopping.load(); });
                    continue;
                }
            }
            DWORD received = 0;
            if (!ReadFile(input, buffer, juce::jmin<DWORD>(available, static_cast<DWORD>(sizeof(buffer))), &received, nullptr) || received == 0) break;
            for (DWORD index = 0; index < received && !stopping; ++index) {
                const char c = buffer[index];
                if (c == '\n') {
                    if (!line.empty() && line.back() == '\r') line.pop_back();
                    if (oversized || !line.empty()) {
                        if (!enqueue({ std::move(line), oversized })) break;
                    }
                    line.clear(); oversized = false;
                } else if (!oversized) {
                    if (line.size() >= maximumLineBytes) { line.clear(); oversized = true; }
                    else line.push_back(c);
                }
            }
        }
        if (!stopping && (oversized || !line.empty())) enqueue({ std::move(line), oversized });
       #else
        std::cerr << "The current local control transport is implemented for Windows.\n";
       #endif
        readerEnded = true;
        if (!stopping) triggerAsyncUpdate();
    }
    void writeLoop()
    {
       #if JUCE_WINDOWS
        const auto output = static_cast<HANDLE>(protocolOutput);
        const auto type = output == nullptr || output == INVALID_HANDLE_VALUE ? FILE_TYPE_UNKNOWN : GetFileType(output);
        if (type != FILE_TYPE_PIPE && type != FILE_TYPE_DISK) {
            std::cerr << "Control stdout must be a redirected pipe or file.\n";
            outputFailed = true; triggerAsyncUpdate(); return;
        }
        for (;;) {
            std::string line;
            {
                std::unique_lock lock(mutex);
                changed.wait(lock, [this] { return stopping || !replies.empty(); });
                if (stopping) break;
                line = std::move(replies.front()); replies.pop_front(); writing = true;
            }
            bool success = output != nullptr && output != INVALID_HANDLE_VALUE;
            for (std::size_t offset = 0; success && offset < line.size() && !stopping;) {
                DWORD written = 0;
                const auto count = static_cast<DWORD>(juce::jmin<std::size_t>(line.size() - offset, 65536));
                success = WriteFile(output, line.data() + offset, count, &written, nullptr) != 0 && written > 0;
                offset += written;
            }
            {
                std::lock_guard lock(mutex);
                writing = false;
            }
            if (!success) outputFailed = true;
            if (!stopping) triggerAsyncUpdate();
            changed.notify_all();
            if (!success) break;
        }
       #endif
    }
    void handleAsyncUpdate() override
    {
        if (stopping || quitNotified) return;
        // A vendor can pump this dispatcher while a project operation owns
        // the Edit. Leave frames queued; the regular timer resumes dispatch
        // after that operation returns, without exposing a half-built state.
        if (session.isControlBusy()) return;
        for (int count = 0; count < 8 && !outputFailed; ++count) {
            Frame frame;
            {
                std::lock_guard lock(mutex);
                if (requests.empty() || replies.size() >= maximumQueuedFrames) break;
                frame = std::move(requests.front()); requests.pop_front();
            }
            changed.notify_all();
            juce::var response;
            try {
                juce::var request;
                if (frame.oversized) response = protocolError("request_too_large", "JSONL requests are limited to 1 MiB.");
                else if (auto result = parseEnvelope(frame.text, request); result.failed())
                    response = protocolError("invalid_json", result.getErrorMessage());
                else response = session.executeRequest(request);
            } catch (const std::exception& error) {
                response = protocolError("internal_error", error.what());
            } catch (...) {
                response = protocolError("internal_error", "Unknown command failure.");
            }
            auto json = juce::JSON::toString(response, true);
            if (json.getNumBytesAsUTF8() > maximumLineBytes)
                json = juce::JSON::toString(protocolError("response_too_large", "Response exceeds 1 MiB; request a smaller range."), true);
            {
                std::lock_guard lock(mutex);
                replies.push_back(json.toStdString() + "\n");
            }
            changed.notify_all();
        }
        bool drained = false, more = false;
        {
            std::lock_guard lock(mutex);
            drained = requests.empty() && replies.empty() && !writing;
            more = !requests.empty() && replies.size() < maximumQueuedFrames;
        }
        if (outputFailed || (readerEnded && drained)) {
            quitNotified = true;
            // Invoke at the tail: the application may destroy this endpoint.
            auto callback = onQuit;
            if (callback) callback();
            return;
        }
        if (more) triggerAsyncUpdate();
    }
    void timerCallback() override { handleAsyncUpdate(); }
};

ControlServer::ControlServer(EngineSession& session, ControlStdio& stdio, std::function<void()> onQuit)
#if JUCE_WINDOWS
    : impl(std::make_unique<Impl>(session, stdio.impl->protocol.value, std::move(onQuit))) {}
#else
    : impl(std::make_unique<Impl>(session, nullptr, std::move(onQuit))) { juce::ignoreUnused(stdio); }
#endif
ControlServer::~ControlServer() = default;
}
