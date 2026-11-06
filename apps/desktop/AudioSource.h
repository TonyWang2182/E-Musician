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
// Optional EMUSICIAN_AUDIO_CACHE_ROOT selects an absolute cache root; PCM
// lives under its audio-v1 child. Unset keeps the historical application cache.
juce::Result prepareSource(const juce::File&, PreparedSource&, const IOOptions& = {});
} // namespace emusician::audio
