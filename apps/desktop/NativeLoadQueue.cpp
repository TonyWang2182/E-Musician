#include "NativeLoadQueue.h"

#include <algorithm>
#include <exception>
#include <limits>

namespace emusician::native {
namespace {
juce::Result defaultLoader(const NativeLoadQueue::Request& request, std::unique_ptr<PreparedBank>& bank)
{
    juce::var state;
    if (auto parsed = juce::JSON::parse(request.stateJson, state); parsed.failed())
        return juce::Result::fail("Cannot parse native device state.");
    return prepareBank(state, request.assets, request.generation, bank, request.reusable.get());
}
}

NativeLoadQueue::NativeLoadQueue(Callback completion, Loader prepare)
    : callback(std::move(completion)), loader(prepare ? std::move(prepare) : Loader(defaultLoader)),
      worker([this] { run(); })
{
    jassert(juce::MessageManager::getInstance()->isThisTheMessageThread());
    startTimer(25);
}

NativeLoadQueue::~NativeLoadQueue()
{
    stopTimer();
    {
        std::lock_guard guard(mutex);
        stopping = true;
        pending.clear();
        entries.clear();
    }
    wake.notify_all();
    // Safe ownership: waits for any current decode, which cannot yet be
    // cancelled mid-read. May block for slow/unresponsive storage.
    if (worker.joinable()) worker.join();
    completed.reset(); // sample data destruction stays off the audio thread
}

juce::Result NativeLoadQueue::submit(Request request, std::uint64_t& token)
{
    jassert(juce::MessageManager::getInstance()->isThisTheMessageThread());
    token = 0;
    if (request.projectId.isEmpty() || request.deviceId.isEmpty() || request.projectId.length() > 128
        || request.deviceId.length() > 128 || request.stateJson.isEmpty()
        || request.stateJson.getNumBytesAsUTF8() > 16 * 1024 || request.assets.size() > 16)
        return juce::Result::fail("Invalid or oversized native sample request.");
    std::lock_guard guard(mutex);
    if (stopping) return juce::Result::fail("Native sample loader is shutting down.");
    const Key key { request.projectId, request.deviceId };
    auto found = entries.find(key);
    if (found == entries.end() && entries.size() >= maxEntries)
        return juce::Result::fail("Too many native devices are tracked by the sample loader.");
    const auto old = std::find_if(pending.begin(), pending.end(), [&](const auto& job) {
        return job.request.projectId == key.first && job.request.deviceId == key.second;
    });
    if (old == pending.end() && pending.size() >= maxPending)
        return juce::Result::fail("Native sample load queue is full. Try again shortly.");
    if (nextToken == std::numeric_limits<std::uint64_t>::max())
        return juce::Result::fail("Native sample load token limit reached.");
    token = nextToken++;
    if (old != pending.end()) pending.erase(old);
    pending.push_back({ std::move(request), token });
    entries[key].status = { Phase::queued, token, {} };
    wake.notify_one();
    return juce::Result::ok();
}

void NativeLoadQueue::cancelDevice(const juce::String& projectId, const juce::String& deviceId)
{
    jassert(juce::MessageManager::getInstance()->isThisTheMessageThread());
    {
        std::lock_guard guard(mutex);
        std::erase_if(pending, [&](const auto& job) {
            return job.request.projectId == projectId && job.request.deviceId == deviceId;
        });
        entries.erase({projectId, deviceId});
        if (completed && completed->request.projectId == projectId && completed->request.deviceId == deviceId)
            completed.reset();
    }
    wake.notify_all();
}

void NativeLoadQueue::cancelProject(const juce::String& projectId)
{
    jassert(juce::MessageManager::getInstance()->isThisTheMessageThread());
    {
        std::lock_guard guard(mutex);
        std::erase_if(pending, [&](const auto& job) { return job.request.projectId == projectId; });
        std::erase_if(entries, [&](const auto& item) { return item.first.first == projectId; });
        if (completed && completed->request.projectId == projectId) completed.reset();
    }
    wake.notify_all();
}

NativeLoadQueue::Status NativeLoadQueue::status(const juce::String& projectId, const juce::String& deviceId) const
{
    std::lock_guard guard(mutex);
    const auto found = entries.find({ projectId, deviceId });
    return found == entries.end() ? Status {} : found->second.status;
}

void NativeLoadQueue::dispatchReady()
{
    jassert(juce::MessageManager::getInstance()->isThisTheMessageThread());
    std::unique_ptr<Completion> result;
    {
        std::lock_guard guard(mutex);
        if (completed) {
            const auto found = entries.find({ completed->request.projectId, completed->request.deviceId });
            if (found != entries.end() && found->second.status.token == completed->token)
                result = std::move(completed);
            else completed.reset();
        }
    }
    wake.notify_one();
    // The callback may destroy the owner/queue, so do not access members after.
    auto target = callback;
    if (result && target) target(std::move(*result));
}

void NativeLoadQueue::run()
{
    for (;;) {
        Job job;
        {
            std::unique_lock lock(mutex);
            wake.wait(lock, [&] { return stopping || (!pending.empty() && !completed); });
            if (stopping) return;
            job = std::move(pending.front()); pending.pop_front();
            auto found = entries.find({job.request.projectId, job.request.deviceId});
            if (found == entries.end() || found->second.status.token != job.token) continue;
            found->second.status.phase = Phase::loading;
        }
        auto output = std::make_unique<Completion>();
        output->request = std::move(job.request); output->token = job.token;
        try {
            output->result = loader(output->request, output->bank);
            if (output->result.wasOk() && !output->bank)
                output->result = juce::Result::fail("Native sample loader returned no prepared bank.");
        } catch (const std::exception&) {
            output->result = juce::Result::fail("Native sample loading failed with an exception.");
        } catch (...) {
            output->result = juce::Result::fail("Native sample loading failed unexpectedly.");
        }
        {
            std::lock_guard guard(mutex);
            if (stopping) return;
            const auto found = entries.find({output->request.projectId, output->request.deviceId});
            if (found == entries.end() || found->second.status.token != output->token) continue;
            found->second.status.phase = output->result.wasOk() ? Phase::prepared : Phase::error;
            found->second.status.error = output->result.getErrorMessage();
            completed = std::move(output);
        }
    }
}
} // namespace emusician::native
