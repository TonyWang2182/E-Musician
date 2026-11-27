#pragma once
#include "EngineSession.h"
#include <functional>
#include <memory>

namespace emusician {
// Read-only mixer projection. Only a curve drag keeps a temporary gesture preview.
class SelectedTrackPanel final : public juce::Component {
public:
    explicit SelectedTrackPanel(EngineSession&);
    ~SelectedTrackPanel() override;
    void update(const EngineSession::Snapshot&);
    void showDevices();
    bool isMasterView() const;
    void resized() override;
    void paint(juce::Graphics&) override;
    std::function<void(const juce::Result&)> onResult;
    std::function<void(const juce::String&)> onBrowsePlugins;
    std::function<void(const juce::String&)> onOpenNative;
    std::function<void(const juce::String&, const juce::String&)> onOpenNativeEffect;
    juce::Result runInteractionSmokeTest(juce::DynamicObject&);
private:
    struct Impl;
    std::unique_ptr<Impl> impl;
};
}
