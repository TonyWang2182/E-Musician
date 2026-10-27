#pragma once
#include <juce_core/juce_core.h>
#include <functional>
#include <memory>

namespace emusician {
class EngineSession;

// Process-scoped stdout isolation for --control-stdio. Construct before the
// engine can load any third-party code and destroy after all plugin instances.
// Only the private, non-inherited handle carries JSONL; ordinary stdout is sent
// to diagnostics and is never restored onto the protocol pipe during shutdown.
class ControlStdio final {
public:
    ControlStdio();
    ~ControlStdio();
    ControlStdio(const ControlStdio&) = delete;
    ControlStdio& operator=(const ControlStdio&) = delete;
    // Explicit CLI test probes, not Agent protocol commands.
    juce::Result runOutputProbe() const;
    static int runOutputProbeChild();
private:
    friend class ControlServer;
    struct Impl;
    std::unique_ptr<Impl> impl;
};

// Opt-in local JSONL control endpoint. The caller owns its lifetime before
// EngineSession and opts into an independent process with --control-stdio.
// EOF drains queued replies, then calls onQuit on the message thread.
class ControlServer final {
public:
    ControlServer(EngineSession&, ControlStdio&, std::function<void()> onQuit);
    ~ControlServer();
    ControlServer(const ControlServer&) = delete;
    ControlServer& operator=(const ControlServer&) = delete;
private:
    struct Impl;
    std::unique_ptr<Impl> impl;
};
}
