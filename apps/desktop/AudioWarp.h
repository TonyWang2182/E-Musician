#pragma once
#include "AudioSource.h"

namespace emusician::audio {
struct WarpRender {
    PreparedSource source;
    juce::String sourceHash, renderHash, cacheKey;
    juce::int64 frames = 0;
};
// File worker only. Fixed ratio, zero pitch shift, bounded buffers, original
// sample rate. Exact output length and latency compensation are verified before
// an atomic cache publication. Failure never publishes unchanged source audio.
juce::Result renderWarp(const PreparedSource& original, double speedRatio, WarpRender&, const IOOptions& = {});
inline constexpr const char* warpRendererVersion = "signalsmith-1.3.2-88061fd4-linear-0.6.6-v1";
}
