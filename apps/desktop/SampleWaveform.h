#pragma once

#include <juce_audio_formats/juce_audio_formats.h>
#include <juce_gui_basics/juce_gui_basics.h>
#include <functional>
#include <memory>

namespace emusician {
namespace native { struct SampleData; }

// A bounded, read-only visualisation of one native sample. Source files are
// checked against the playing bank's SHA-256 before waveform data is shown.
// Its shared serial worker never touches the audio callback or UI components.
class SampleWaveform final : public juce::Component, private juce::Timer {
public:
    SampleWaveform();
    ~SampleWaveform() override;

    void setSource(const juce::File&, const juce::String& expectedSha256,
                   std::shared_ptr<const native::SampleData> prepared = {});
    // The owning dock explicitly suspends polling while hidden; visibility
    // changes of an ancestor need not notify JUCE child Components.
    void setActive(bool);
    // Positions are normalized to the actual decoded sample [0, 1]. Changes
    // during a gesture are local previews until onRangeCommit is called.
    void setRange(double start, double end, bool editable);
    void cancelDrag();
    bool isReady() const;
    double durationSeconds() const;
    juce::String statusText() const;

    std::function<void()> onRangeDragStart;
    std::function<void(double, double)> onRangeCommit;
    std::function<void()> onRangeCancel;

    void paint(juce::Graphics&) override;
    void mouseDown(const juce::MouseEvent&) override;
    void mouseDrag(const juce::MouseEvent&) override;
    void mouseUp(const juce::MouseEvent&) override;
    bool keyPressed(const juce::KeyPress&) override;

    // Generates its own disposable WAV under outputDirectory and verifies the
    // real worker, source hash checks, cache, stale result and gestures.
    static juce::Result runSmokeTest(const juce::File& outputDirectory);

private:
    struct Impl;
    std::unique_ptr<Impl> impl;
    void timerCallback() override;
};
}
