// Include inside namespace emusician after NativeLoadQueue.h is included at
// translation-unit scope. Injected loader and owned fake banks; no disk/DAW.
juce::Result runNativeLoadQueueTests()
{
    using Queue = native::NativeLoadQueue;
    juce::WaitableEvent began, unblock;
    struct Release { juce::WaitableEvent& event; ~Release() { event.signal(); } };
    std::atomic<int> calls {0};
    std::vector<std::uint64_t> delivered;
    bool messageThread = true;
    Queue queue([&](Queue::Completion result) {
        messageThread &= juce::MessageManager::getInstance()->isThisTheMessageThread();
        if (result.result.wasOk() && result.bank) delivered.push_back(result.token);
    }, [&](const Queue::Request& request, std::unique_ptr<native::PreparedBank>& output) {
        ++calls;
        if (request.revision == 1) {
            began.signal();
            if (!unblock.wait(5000)) return juce::Result::fail("Test loader was not released.");
        }
        if (request.revision == 99) return juce::Result::fail("Synthetic load error");
        output = std::make_unique<native::PreparedBank>();
        output->bank.generation = request.generation;
        return juce::Result::ok();
    });
    Release release {unblock};
    const auto request = [](const juce::String& project, const juce::String& device, std::uint64_t revision) {
        Queue::Request r; r.projectId = project; r.deviceId = device; r.stateJson = "{}";
        r.revision = revision; r.generation = revision; return r;
    };
    const auto wait = [&](const juce::String& project, const juce::String& device, Queue::Phase wanted) {
        for (int i = 0; i < 2000; ++i) {
            if (queue.status(project, device).phase == wanted) return true;
            juce::Thread::sleep(1);
        }
        return false;
    };
    std::uint64_t first = 0, second = 0, third = 0, cancelled = 0;
    if (queue.submit(request("p", "a", 1), first).failed() || !began.wait(2000))
        return juce::Result::fail("Loader did not start.");
    if (queue.submit(request("p", "a", 2), second).failed()
        || queue.submit(request("p", "a", 3), third).failed()
        || queue.submit(request("q", "b", 4), cancelled).failed())
        return juce::Result::fail("Could not enqueue coalescing fixtures.");
    if (!(first < second && second < third && third < cancelled)
        || queue.status("p", "a").token != third)
        return juce::Result::fail("Latest queued token was not retained.");
    queue.cancelProject("q");
    unblock.signal();
    if (!wait("p", "a", Queue::Phase::prepared)) return juce::Result::fail("Latest bank did not finish.");
    queue.dispatchReady();
    if (!messageThread || delivered.size() != 1 || delivered[0] != third || calls.load() != 2
        || queue.status("q", "b").phase != Queue::Phase::idle)
        return juce::Result::fail("A stale or cancelled bank was delivered, or delivery was not on the message thread.");

    std::uint64_t error = 0;
    if (queue.submit(request("p", "a", 99), error).failed() || !wait("p", "a", Queue::Phase::error))
        return juce::Result::fail("Worker error status was not exposed.");
    queue.dispatchReady();
    if (delivered.size() != 1 || queue.status("p", "a").error.isEmpty())
        return juce::Result::fail("Worker error was mistaken for successful publication.");
    queue.cancelDevice("p", "a");
    if (queue.status("p", "a").phase != Queue::Phase::idle)
        return juce::Result::fail("Device cancellation did not clear status.");
    return juce::Result::ok();
}
