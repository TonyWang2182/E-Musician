// Included as a block in runDawSmokeTest. Deliberately do not pump messages:
// a timer tick would hide the terminal-worker/immediate-retry regression.
{
    const auto checksBeforeRetry = checks;
    const auto waitWorker = [&](const std::shared_ptr<Impl::Job>& job) {
        const auto deadline = juce::Time::getMillisecondCounterHiRes() + 15000.0;
        while (!job->done.load(std::memory_order_acquire)
               && juce::Time::getMillisecondCounterHiRes() < deadline) {
            if (job->preparation) { auto step = job->preparation; step(); }
            juce::Thread::sleep(1);
        }
        check(job->done.load(std::memory_order_acquire), "job retry worker completes within test timeout");
    };
    const auto jobState = [](const std::shared_ptr<Impl::Job>& job) {
        std::lock_guard lock(job->mutex);
        return job->status;
    };
    const auto saveArgs = [&](const juce::File& file) { return object({{"path", file.getFullPathName()}}); };
    const auto failedFile = workspace.getChildFile("retry-invalid.emproj");
    const auto retryFile = workspace.getChildFile("retry-valid.emproj");
    const auto forbiddenFile = workspace.getChildFile("retry-must-not-start.emproj");
    const juce::String invalidManifest = "owned invalid manifest";
    check(!failedFile.exists() && failedFile.replaceWithText(invalidManifest), "create owned invalid save destination");
    command(*this, "set_master_gain", object({{"gain_db", -11.0}}));
    command(*this, "save_project", saveArgs(failedFile));
    const auto failedJob = impl->jobs.back();
    waitWorker(failedJob);
    check(jobState(failedJob) == "failed" && failedJob->worker.joinable(),
          "failed Save is observable before timer reaps its worker");
    check(failedFile.loadFileAsString() == invalidManifest, "failed Save preserves invalid destination bytes");
    const auto revisionBeforeRetry = snapshot().revision;
    command(*this, "save_project", saveArgs(retryFile));
    const auto retryJob = impl->jobs.back();
    check(retryJob != failedJob && !failedJob->worker.joinable(),
          "immediate Save retry retires completed failed worker and accepts a new job");
    check(snapshot().revision == revisionBeforeRetry, "retiring failed worker does not mutate project revision");
    waitWorker(retryJob);
    {
        std::lock_guard lock(retryJob->mutex);
        check(bool(retryJob->commit), "successful Save awaits its original commit");
    }
    const auto jobsBeforePending = impl->jobs.size();
    check(execute("save_project", saveArgs(forbiddenFile), snapshot().revision).failed(),
          "pending Save commit remains a conflict boundary for new requests");
    check(impl->jobs.size() == jobsBeforePending && retryJob->worker.joinable() && !forbiddenFile.exists(),
          "admission neither applies pending commit nor starts a competing writer");
    command(*this, "set_master_gain", object({{"gain_db", -12.0}}));
    impl->reapFinishedJobs(true);
    check(jobState(retryJob) == "completed" && snapshot().dirty,
          "Save commit preserves a newer edit made after snapshot capture");
    storage::StoredProject retryStored;
    okay(storage::load(retryFile, retryStored), "load retry manifest");
    check(std::abs(retryStored.masterGainDb + 11.0f) < 0.001f
          && std::abs(impl->capture().masterGainDb + 12.0f) < 0.001f,
          "saved snapshot and newer live edit remain distinct");
    command(*this, "save_project", saveArgs(retryFile));
    const auto finalSave = impl->jobs.back();
    waitWorker(finalSave);
    impl->reapFinishedJobs(true);
    okay(storage::load(retryFile, retryStored), "load latest retry manifest");
    check(jobState(finalSave) == "completed" && !snapshot().dirty
          && std::abs(retryStored.masterGainDb + 12.0f) < 0.001f,
          "next Save persists the newer edit and clears dirty state");

    // A gate makes active-worker admission deterministic instead of relying on
    // disk speed. Its deadline bounds cleanup even if a future regression joins.
    auto release = std::make_shared<std::atomic<bool>>(false);
    const auto liveJob = impl->startJob("retry_active_fixture", [release](const auto& job) {
        const auto deadline = juce::Time::getMillisecondCounterHiRes() + 2000.0;
        while (!release->load(std::memory_order_acquire) && !job->cancel.load()
               && juce::Time::getMillisecondCounterHiRes() < deadline)
            juce::Thread::sleep(1);
        jobStatus(job, "cancelled");
    });
    check(bool(liveJob), "start gated active worker fixture");
    const auto liveResult = execute("save_project", saveArgs(forbiddenFile), snapshot().revision);
    const bool returnedWhileActive = !liveJob->done.load(std::memory_order_acquire);
    release->store(true, std::memory_order_release);
    waitWorker(liveJob);
    check(liveResult.failed() && returnedWhileActive && !forbiddenFile.exists(),
          "Save rejects active worker without waiting for its completion");
    impl->reapFinishedJobs(false);
    check(!liveJob->worker.joinable(), "terminal cancelled worker can be retired at admission");

    auto applied = std::make_shared<int>(0);
    const auto pendingImport = impl->startJob("import_audio", [applied](const auto& job) {
        std::lock_guard lock(job->mutex);
        job->commit = [applied] { ++*applied; };
    });
    check(bool(pendingImport), "start pending import commit fixture");
    waitWorker(pendingImport);
    check(execute("save_project", saveArgs(forbiddenFile), snapshot().revision).failed()
          && *applied == 0 && pendingImport->worker.joinable(),
          "admission does not recursively apply pending project replacement");
    command(*this, "set_master_gain", object({{"gain_db", -13.0}}));
    impl->reapFinishedJobs(true);
    check(jobState(pendingImport) == "conflict" && *applied == 0,
          "normal completion still rejects an import captured at an older revision");
    const auto report = object({{"schema_version", 1}, {"test_version", 1}, {"status", "passed"},
        {"checks", checks - checksBeforeRetry},
        {"scope", "Real invalid-destination Save and immediate retry without timer pumping; newer edit retention; gated active worker; pending import revision conflict"}});
    check(directory.getChildFile("job-retry-report.json").replaceWithText(juce::JSON::toString(report)),
          "write job retry regression report");
}
