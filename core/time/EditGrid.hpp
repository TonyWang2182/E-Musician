#pragma once
#include <algorithm>
#include <cmath>

namespace emusician::time {
// Quarter-note beats throughout; meter changes only bar boundaries and labels.
inline double editGridBeats(double fixed, bool adaptive, double visibleBeats, double pixels)
{
    if (!adaptive) return std::max(1.0 / 128.0, fixed);
    const double wanted = std::max(1.0 / 128.0, visibleBeats * 18.0 / std::max(1.0, pixels));
    return std::clamp(std::pow(2.0, std::ceil(std::log2(wanted))), 1.0 / 128.0, 64.0);
}
inline double snapEditBeat(double value, double grid)
{
    return grid > 0.0 ? std::round(value / grid) * grid : value;
}
inline double beatsPerBar(int numerator, int denominator)
{
    return std::max(1, numerator) * 4.0 / std::max(1, denominator);
}
}
