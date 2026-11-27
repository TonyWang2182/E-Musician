#pragma once
#include "EngineSession.h"
#include <functional>
#include <memory>

namespace emusician {
// A view of one existing effect, or an add prompt. The Edit remains authoritative.
class NativeEffectsPanel final : public juce::Component, private juce::Timer {
public:
    NativeEffectsPanel(EngineSession&, juce::String trackId, juce::String deviceId,
                       std::function<void(const juce::Result&)>);
    ~NativeEffectsPanel() override;
    void paint(juce::Graphics&) override;
    void resized() override;
    void visibilityChanged() override;
    juce::Result runInteractionSmokeTest(juce::DynamicObject&, const juce::File&);
private:
    struct Impl;
    std::unique_ptr<Impl> impl;
    void timerCallback() override;
};
}
