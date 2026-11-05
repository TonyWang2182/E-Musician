#pragma once
#include "EngineSession.h"
#include <functional>
#include <memory>

namespace emusician {
// One-track view over the authoritative EngineSession; no audio or sample data is owned here.
class NativeDevicePanel final : public juce::Component, private juce::Timer {
public:
    NativeDevicePanel(EngineSession&, juce::String trackId, std::function<void(const juce::Result&)>);
    ~NativeDevicePanel() override;
    void paint(juce::Graphics&) override;
    void resized() override;
    void visibilityChanged() override;
    juce::Result runInteractionSmokeTest(juce::DynamicObject&, const juce::File&);
private:
    struct Impl;
    std::unique_ptr<Impl> impl;
    void timerCallback() override;
    void updatePollingInterval();
};
}
