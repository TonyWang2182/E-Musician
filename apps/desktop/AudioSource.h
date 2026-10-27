#pragma once

#include <juce_audio_formats/juce_audio_formats.h>
#include <functional>

namespace emusician::audio {
struct PreparedSource {
    juce::File playbackFile;
    double duration = 0.0, sampleRate = 0.0;
    int channels = 0;
    juce::String format;
};
struct IOOptions {
    std::function<bool()> cancelled;
    std::function<void(double fraction, const juce::String& stage)> progress;
};

// Control/import-thread preparation. MP3 is decoded sequentially to a versioned,
// content-addressed PCM cache, shared by waveform and engine playback. Originals
// are never modified. The output argument is assigned only after success.
juce::Result prepareSource(const juce::File&, PreparedSource&, const IOOptions& = {});
} // namespace emusician::audio
