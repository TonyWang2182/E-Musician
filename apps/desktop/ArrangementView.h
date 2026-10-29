#pragma once
#include "EngineSession.h"
#include <functional>
#include <memory>

namespace emusician {
// Read-only projection of EngineSession. Selection and transport use its command API.
class ArrangementView final : public juce::Component {
public:
    explicit ArrangementView(EngineSession&);
    ~ArrangementView() override;
    void update(const EngineSession::Snapshot&);
    void invalidateSources();
    void fitToProject();
    void zoomIn();
    void zoomOut();
    double zoomFactor() const;
    void setDropActive(bool);
    bool isDropActive() const;
    bool cancelClipDrag();
    juce::StringArray selectedClipIds() const;
    void setGrid(double beats, bool bars);
    void setRulerMode(int mode); // 0: bars/beats, 1: minutes/seconds, 2: both
    void setGridBeats(double beats);
    void setSnapEnabled(bool enabled);
    void setAdaptiveGrid(bool enabled);
    void setFollowPlayhead(bool enabled);
    juce::Range<double> selectedTimeRange() const;
    void selectClipIds(const juce::StringArray&);
    juce::Result loopSelection();
    void setCompactRows(bool);
    bool waveformsReady() const;
    bool trackWaveformReady(const juce::String&) const;
    juce::String waveformStatus(const juce::String&) const;
    void drawTrackWaveform(juce::Graphics&, juce::Rectangle<int>, const juce::String&,
                           double start, double end, float verticalZoom);
    juce::Result runSmokeTest(juce::DynamicObject& report, const juce::File& outputDirectory = {});
    void paint(juce::Graphics&) override;
    void resized() override;
    void mouseDown(const juce::MouseEvent&) override;
    void mouseDrag(const juce::MouseEvent&) override;
    void mouseUp(const juce::MouseEvent&) override;
    void mouseWheelMove(const juce::MouseEvent&, const juce::MouseWheelDetails&) override;
    bool keyPressed(const juce::KeyPress&) override;
    void focusGained(FocusChangeType) override;
    void focusLost(FocusChangeType) override;
    void focusOfChildComponentChanged(FocusChangeType) override;
    std::function<void()> onUserStateChange;
    std::function<void(const juce::Result&)> onEditResult;
    std::function<void(const juce::String&)> onOpenMidiClip;
    std::function<void(const juce::String&)> onOpenTrackDevices;
private:
    struct Impl;
    std::unique_ptr<Impl> impl;
    JUCE_DECLARE_NON_COPYABLE_WITH_LEAK_DETECTOR(ArrangementView)
};
}
