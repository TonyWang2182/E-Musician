#pragma once

#include "NativeInstrument.h"
#include <condition_variable>
#include <cstdint>
#include <deque>
#include <functional>
#include <map>
#include <mutex>
#include <thread>

namespace emusician::native {

// Own on the JUCE message thread. Neither methods nor callback are for use on
// the audio thread. Completion means decoded, not installed or audible.
class NativeLoadQueue final : private juce::Timer {
public:
    struct Request {
        juce::String projectId, deviceId, stateJson;
        std::uint64_t revision = 0, generation = 0;
        std::map<juce::String, juce::File> assets;
        // Present only for parameter-only edits of a ready device. Immutable
        // PCM can be reused without touching its source files.
        std::shared_ptr<const PreparedBank> reusable;
    };
    enum class Phase { idle, queued, loading, prepared, error };
    struct Status { Phase phase = Phase::idle; std::uint64_t token = 0; juce::String error; };
    struct Completion {
        Request request;
        std::uint64_t token = 0;
        juce::Result result = juce::Result::ok();
        std::unique_ptr<PreparedBank> bank;
    };
    using Callback = std::function<void(Completion)>;
    // Dependency injection permits deterministic queue tests without disk IO.
    using Loader = std::function<juce::Result(const Request&, std::unique_ptr<PreparedBank>&)>;

    explicit NativeLoadQueue(Callback, Loader = {});
    ~NativeLoadQueue() override;
    NativeLoadQueue(const NativeLoadQueue&) = delete;
    NativeLoadQueue& operator=(const NativeLoadQueue&) = delete;

    // At most 16 pending requests, one decoding request and one prepared bank.
    // Pending requests for the same project+device are replaced. The returned
    // token is unique within this queue instance, not a project revision.
    juce::Result submit(Request, std::uint64_t& token);
    void cancelDevice(const juce::String& projectId, const juce::String& deviceId);
    void cancelProject(const juce::String& projectId);
    Status status(const juce::String& projectId, const juce::String& deviceId) const;
    // Message-thread delivery; public for deterministic tests. The owner must
    // check project/device/revision/generation again before publishing.
    void dispatchReady();

private:
    using Key = std::pair<juce::String, juce::String>;
    struct Job { Request request; std::uint64_t token = 0; };
    struct Entry { Status status; };
    static constexpr std::size_t maxPending = 16, maxEntries = 128;
    mutable std::mutex mutex;
    std::condition_variable wake;
    std::deque<Job> pending;
    std::map<Key, Entry> entries;
    std::unique_ptr<Completion> completed;
    std::uint64_t nextToken = 1;
    bool stopping = false;
    Callback callback;
    Loader loader;
    std::thread worker;
    void run();
    void timerCallback() override { dispatchReady(); }
};

} // namespace emusician::native
