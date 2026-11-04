#pragma once
#include "EngineSession.h"
#include <functional>
#include <memory>

namespace emusician {
// Shared snapshot projection; controls reuse the engine command and gesture APIs.
// Compact is the persistent selected-track / Master rail; expanded shows all tracks.
class MixerView final : public juce::Component {
public:
    explicit MixerView(EngineSession&);
    ~MixerView() override;
    void update(const EngineSession::Snapshot&);
    void setCompact(bool);
    void resized() override;
    void paint(juce::Graphics&) override;
    std::function<void(const juce::Result&)> onResult;
    std::function<void(const juce::String&)> onBrowsePlugins;
    std::function<void(const juce::String&)> onShowTrackDetails;
    std::function<void()> onUserStateChange;
    juce::Result runInteractionSmokeTest(juce::DynamicObject&);
private:
    struct Impl;
    std::unique_ptr<Impl> impl;
};
}
