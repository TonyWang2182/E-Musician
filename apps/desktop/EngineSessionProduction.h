#pragma once

#include "ProjectStorage.h"
#include "../../core/AudioDeviceConfiguration.h"
#include <tracktion_engine/tracktion_engine.h>
#include <memory>

namespace emusician::production {
// Message-thread helpers. These operate on the authoritative Edit and use DTOs
// only while validating/applying a command or capturing persistence state.
juce::Result validateGraph(const storage::StoredProject&);
void captureGraph(tracktion::Edit&, storage::StoredProject&, bool includeControllers = true);
juce::Result applyGraph(tracktion::Edit&, const storage::StoredProject&, bool loading);
juce::Result mutateGraph(storage::StoredProject&, const juce::String&, const juce::var&);
juce::var automationTargets(tracktion::Edit&, const juce::String& trackId);

class RecordingController final {
public:
    explicit RecordingController(tracktion::Engine&);
    ~RecordingController();
    void attach(tracktion::Edit&, const juce::File& recordingDirectory);
    void detach();
    juce::Result execute(const juce::String&, const juce::var&);
    juce::var state() const;
    juce::var preferences() const;
    // Device lists are refreshed only on explicit requests, never by the UI timer.
    juce::var inputs() const;
    // Control-thread only; do not retain the pointer across a device change.
    tracktion::InputDevice* inputForId(const juce::String&) const;
    juce::var audioDevices(bool scan = false) const;
    // True once after a completed take's clips/notes/assets have been adopted.
    // Caller rebuilds bindings/asset preparation before remembering one revision.
    bool poll();
private:
    struct State;
    std::unique_ptr<State> data;
};
} // namespace emusician::production
