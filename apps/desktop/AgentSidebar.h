#pragma once
#include <juce_gui_extra/juce_gui_extra.h>
#include <functional>
#include <memory>
namespace emusician {
class AgentSidebar final : public juce::Component, private juce::Timer {
public:
    explicit AgentSidebar(std::function<juce::var(const juce::var&)> dispatch);
    ~AgentSidebar() override;
    void setPanelVisible(bool);
    bool isReady() const;
    bool isWorkerRunning() const;
    bool capturesKeyboard() const;
    void clearKeyboardFocusHint();
    juce::String diagnostic() const;
    void restartWorker();
    void refreshLanguage();
    void stopWorkerForTest();
    void evaluateForTest(const juce::String&, juce::WebBrowserComponent::EvaluationCallback);
    void probeStateForTest(juce::WebBrowserComponent::EvaluationCallback);
    void resized() override;
    void paint(juce::Graphics&) override;
    std::function<void()> onClose;
private:
    struct Impl;
    std::unique_ptr<Impl> impl;
    void timerCallback() override;
    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR(AgentSidebar)
};
}
