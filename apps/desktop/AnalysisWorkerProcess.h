#pragma once
#include <juce_core/juce_core.h>
#include <cstdint>
#include <vector>
#if JUCE_WINDOWS
 #ifndef NOMINMAX
  #define NOMINMAX
 #endif
 #ifndef WIN32_LEAN_AND_MEAN
  #define WIN32_LEAN_AND_MEAN
 #endif
 #include <windows.h>
 #include <psapi.h>
#endif

namespace emusician::analysis_worker {
constexpr std::uint64_t gib = 1024ULL * 1024ULL * 1024ULL;
struct Resources {
    bool available = false;
    std::uint64_t commit = 0, physical = 0;
};
struct Policy {
    std::uint64_t minimumCommit = 0;
    static constexpr std::uint64_t minimumPhysical = gib / 2, criticalCommit = gib / 2;
    static constexpr int criticalGraceMs = 1000;
    static Policy forKind(const juce::String& kind) { return {kind == "separate" ? 4*gib : kind == "chords" ? gib : 2*gib}; }
    juce::var json() const {
        auto* value = new juce::DynamicObject();
        value->setProperty("version", 1);
        value->setProperty("minimum_available_commit_bytes", juce::int64(minimumCommit));
        value->setProperty("minimum_available_physical_bytes", juce::int64(minimumPhysical));
        value->setProperty("critical_available_commit_bytes", juce::int64(criticalCommit));
        value->setProperty("critical_grace_ms", criticalGraceMs);
        return value;
    }
    juce::Result admit(Resources memory) const {
#if JUCE_WINDOWS
        if (!memory.available) return juce::Result::fail("Cannot query Windows memory headroom. Analysis was not started.");
#else
        if (!memory.available) return juce::Result::ok();
#endif
        if (memory.commit < minimumCommit || memory.physical < minimumPhysical)
            return juce::Result::fail("Not enough available system memory for analysis (commit "
                + juce::String(double(memory.commit)/double(gib), 2) + " GiB; minimum "
                + juce::String(double(minimumCommit)/double(gib), 1)
                + " GiB; physical " + juce::String(double(memory.physical)/double(gib), 2)
                + " GiB; minimum 0.5 GiB). Close memory-heavy apps before retrying; the project is unchanged.");
        return juce::Result::ok();
    }
};
inline Resources resources() {
#if JUCE_WINDOWS
    PERFORMANCE_INFORMATION state{}; state.cb = sizeof(state);
    if (K32GetPerformanceInfo(&state, sizeof(state))) return {true,
        std::uint64_t(state.CommitLimit >= state.CommitTotal ? state.CommitLimit-state.CommitTotal : 0)*state.PageSize,
        std::uint64_t(state.PhysicalAvailable)*state.PageSize};
#endif
    return {};
}
struct CriticalPressure {
    double since = -1;
    bool shouldStop(Resources memory, double now) {
        if (!memory.available || memory.commit >= Policy::criticalCommit) { since = -1; return false; }
        if (since < 0) since = now;
        return now-since >= Policy::criticalGraceMs;
    }
};
inline juce::String exitFailure(std::uint32_t code) {
    const auto hexadecimal = "0x" + juce::String::toHexString(code).paddedLeft('0', 8);
    if (code == 8 || code == 14 || code == 0xc0000017U || code == 0xc000012dU)
        return "The isolated analysis worker ran out of memory ("+hexadecimal+"). The project is unchanged. See process.log.";
    if (code == 0xc0000005U)
        return "The isolated analysis worker crashed with an access violation ("+hexadecimal+"). The project is unchanged. See process.log.";
    return "The isolated analysis worker exited ("+hexadecimal+") without a valid result. See process.log.";
}

// This object is owned entirely by the file worker, never the message/audio
// thread. A suspended child joins its private Job Object before running Python.
// Windows suppresses unhandled-exception dialogs for the job and closes its
// process tree when this owner goes away; no global ErrorMode is changed.
class Process final {
public:
    Process() = default;
    ~Process() { terminate(); }
    Process(const Process&) = delete;
    Process& operator=(const Process&) = delete;
    juce::Result start(const juce::StringArray& arguments, const juce::File& log) {
        if (arguments.isEmpty()) return juce::Result::fail("Missing analysis worker command.");
#if JUCE_WINDOWS
        const auto failure = [](const char* text) {
            return juce::Result::fail(juce::String(text)+" (Windows "+juce::String(GetLastError())+").");
        };
        job.value = CreateJobObjectW(nullptr, nullptr);
        if (!job.valid()) return failure("Cannot create isolated analysis job");
        JOBOBJECT_EXTENDED_LIMIT_INFORMATION limits{};
        limits.BasicLimitInformation.LimitFlags = JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE | JOB_OBJECT_LIMIT_DIE_ON_UNHANDLED_EXCEPTION;
        if (!SetInformationJobObject(job.value, JobObjectExtendedLimitInformation, &limits, sizeof(limits)))
            return failure("Cannot configure isolated analysis job");
        SECURITY_ATTRIBUTES security{sizeof(SECURITY_ATTRIBUTES), nullptr, TRUE};
        Handle output, input;
        output.value = CreateFileW(log.getFullPathName().toWideCharPointer(), GENERIC_WRITE, FILE_SHARE_READ | FILE_SHARE_WRITE,
                                  &security, CREATE_ALWAYS, FILE_ATTRIBUTE_NORMAL, nullptr);
        input.value = CreateFileW(L"NUL", GENERIC_READ, FILE_SHARE_READ | FILE_SHARE_WRITE,
                                 &security, OPEN_EXISTING, FILE_ATTRIBUTE_NORMAL, nullptr);
        if (!output.valid() || !input.valid()) return failure("Cannot open analysis process log");
        SIZE_T bytes = 0;
        InitializeProcThreadAttributeList(nullptr, 1, 0, &bytes);
        std::vector<unsigned char> buffer(bytes);
        auto* attributes = reinterpret_cast<LPPROC_THREAD_ATTRIBUTE_LIST>(buffer.data());
        if (!InitializeProcThreadAttributeList(attributes, 1, 0, &bytes)) return failure("Cannot initialize worker handle isolation");
        struct DeleteAttributes { LPPROC_THREAD_ATTRIBUTE_LIST value; ~DeleteAttributes(){DeleteProcThreadAttributeList(value);} } cleanup{attributes};
        HANDLE inherited[]{input.value, output.value};
        if (!UpdateProcThreadAttribute(attributes, 0, PROC_THREAD_ATTRIBUTE_HANDLE_LIST, inherited, sizeof(inherited), nullptr, nullptr))
            return failure("Cannot isolate worker handles");
        STARTUPINFOEXW startup{}; startup.StartupInfo.cb = sizeof(startup);
        startup.StartupInfo.dwFlags = STARTF_USESTDHANDLES;
        startup.StartupInfo.hStdInput = input.value; startup.StartupInfo.hStdOutput = output.value; startup.StartupInfo.hStdError = output.value;
        startup.lpAttributeList = attributes;
        std::wstring command;
        for (const auto& arg : arguments) { if (!command.empty()) command += L' '; command += quote(arg); }
        PROCESS_INFORMATION created{};
        if (!CreateProcessW(arguments[0].toWideCharPointer(), command.data(), nullptr, nullptr, TRUE,
            CREATE_NO_WINDOW | CREATE_UNICODE_ENVIRONMENT | CREATE_SUSPENDED | EXTENDED_STARTUPINFO_PRESENT | BELOW_NORMAL_PRIORITY_CLASS,
            nullptr, nullptr, &startup.StartupInfo, &created)) return failure("Cannot start isolated analysis worker");
        process.value = created.hProcess; Handle thread; thread.value = created.hThread;
        if (!AssignProcessToJobObject(job.value, process.value)) {
            const auto result = failure("Cannot attach isolated analysis worker");
            TerminateProcess(process.value, ERROR_CANCELLED); WaitForSingleObject(process.value, 2000); return result;
        }
        if (ResumeThread(thread.value) == DWORD(-1)) return failure("Cannot resume isolated analysis worker");
        return juce::Result::ok();
#else
        juce::ignoreUnused(log);
        return process.start(arguments, 0) ? juce::Result::ok() : juce::Result::fail("Cannot start isolated analysis worker.");
#endif
    }
    bool isRunning() const {
#if JUCE_WINDOWS
        return process.valid() && WaitForSingleObject(process.value, 0) == WAIT_TIMEOUT;
#else
        return process.isRunning();
#endif
    }
    bool wait(int milliseconds) const {
#if JUCE_WINDOWS
        return !process.valid() || WaitForSingleObject(process.value, DWORD(milliseconds)) == WAIT_OBJECT_0;
#else
        return process.waitForProcessToFinish(milliseconds);
#endif
    }
    void terminate() noexcept {
#if JUCE_WINDOWS
        if (job.valid()) TerminateJobObject(job.value, ERROR_CANCELLED);
        if (process.valid()) WaitForSingleObject(process.value, 2000);
#else
        if (process.isRunning()) { process.kill(); process.waitForProcessToFinish(2000); }
#endif
    }
    std::uint32_t exitCode() const {
#if JUCE_WINDOWS
        DWORD code = 0xffffffffU;
        if (process.valid()) GetExitCodeProcess(process.value, &code);
        return code;
#else
        return process.getExitCode();
#endif
    }
private:
#if JUCE_WINDOWS
    struct Handle {
        HANDLE value = nullptr;
        bool valid() const { return value != nullptr && value != INVALID_HANDLE_VALUE; }
        ~Handle() { if (valid()) CloseHandle(value); }
    } job, process;
    static std::wstring quote(const juce::String& text) {
        std::wstring result = L"\""; size_t slashes = 0;
        for (const auto character : std::wstring(text.toWideCharPointer())) {
            if (character == L'\\') { ++slashes; continue; }
            result.append(character == L'"' ? slashes*2+1 : slashes, L'\\');
            slashes = 0; result += character;
        }
        result.append(slashes*2, L'\\'); result += L'"'; return result;
    }
#else
    mutable juce::ChildProcess process;
#endif
};
}
