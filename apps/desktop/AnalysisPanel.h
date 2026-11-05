#pragma once
#include "EngineSession.h"
#include <functional>
#include <memory>

namespace emusician {
// A read-only projection of local analysis jobs. Every action uses the same
// EngineSession commands as the Agent; inference and audio I/O live elsewhere.
class AnalysisPanel final : public juce::Component, private juce::Timer {
public:
    AnalysisPanel(EngineSession&, std::function<void(const juce::Result&)>);
    ~AnalysisPanel() override;
    void paint(juce::Graphics&) override;
    void resized() override;
    void visibilityChanged() override;
    void setSelectedTimeRange(double startSeconds, double endSeconds);
    void showChordRegion(const juce::String& chordId);
    void refreshLanguage();
    juce::Result runInteractionSmokeTest(juce::DynamicObject&, const juce::File&);
private:
    struct Impl;
    std::unique_ptr<Impl> impl;
    void timerCallback() override;
};
}
