#pragma once
#include <juce_audio_utils/juce_audio_utils.h>
#include <memory>

namespace emusician {
// Dedicated audition stream. Disk decoding/resampling and buffer retirement
// happen on its worker. The audio callback only copies a bounded SPSC ring.
class AnalysisPreview final {
public:
    explicit AnalysisPreview(juce::AudioDeviceManager&);
    ~AnalysisPreview();
    juce::Result prepareAndPlay(const juce::File& verifiedArtifact);
    void stop();
    juce::var status() const;
    static juce::Result runSmokeTest(juce::DynamicObject&, const juce::File&);
private:
    struct Impl;
    std::unique_ptr<Impl> impl;
};
}
