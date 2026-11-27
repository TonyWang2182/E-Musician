#pragma once
#include "EngineSession.h"
#include <memory>

namespace emusician {
class GenerationPanel final : public juce::Component, private juce::Timer {
public:
    explicit GenerationPanel(EngineSession&);
    ~GenerationPanel() override;
    void paint(juce::Graphics&) override;
    void resized() override;
    void visibilityChanged() override;
    void refreshLanguage();
    juce::Result runInteractionSmokeTest(const juce::File&);
private:
    struct Impl;std::unique_ptr<Impl> impl;
    void timerCallback() override;
};
}
