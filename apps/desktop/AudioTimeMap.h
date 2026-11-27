#pragma once
#include <cmath>

namespace emusician::audio {
// One affine map for fixed-ratio Warp. Source coordinates always refer to the
// immutable original PCM; playback coordinates refer to the rendered PCM.
struct TimeMap {
    double sourceOffset = 0, timelineStart = 0, speedRatio = 1;
    double sourceAt(double timelineSeconds) const { return sourceOffset + (timelineSeconds - timelineStart) * speedRatio; }
    double timelineAt(double sourceSeconds) const { return timelineStart + (sourceSeconds - sourceOffset) / speedRatio; }
    double playbackOffset() const { return sourceOffset / speedRatio; }
    bool valid() const { return std::isfinite(sourceOffset) && sourceOffset >= 0 && std::isfinite(timelineStart)
        && timelineStart >= 0 && std::isfinite(speedRatio) && speedRatio > 0; }
};
}
