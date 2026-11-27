#pragma once
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <string>

namespace emusician::time {
// All positions use quarter-note beats; 1/16384 of a whole note is 1/4096 beat.
inline constexpr double minimumEditGridBeats = 1.0 / 4096.0;
inline constexpr double minimumEditSpanSeconds = 1.0e-6;
inline double editGridBeats(double fixed, bool adaptive, double visibleBeats, double pixels)
{
    if (!adaptive) return std::isfinite(fixed) ? std::max(minimumEditGridBeats, fixed) : 0.25;
    if (!std::isfinite(visibleBeats) || !std::isfinite(pixels)) return 0.25;
    const double wanted = std::max(minimumEditGridBeats, std::max(0.0, visibleBeats) * 16.0 / std::max(1.0, pixels));
    return std::clamp(std::pow(2.0, std::ceil(std::log2(wanted) - 1.0e-10)), minimumEditGridBeats, 64.0);
}
inline double snapEditBeat(double value, double grid)
{
    return grid > 0.0 && std::isfinite(grid) ? std::round(value / grid) * grid : value;
}
inline double beatsPerBar(int numerator, int denominator)
{
    return std::max(1, numerator) * 4.0 / std::max(1, denominator);
}
struct MusicalRulerGrid { double stepBeats; int labelTier; };
// Ruler labels and edit-grid strokes have independent density. Labels stop at
// quarters of a meter beat; deeper zoom adds strokes, never a fourth name level.
inline MusicalRulerGrid musicalRulerStep(double visibleQuarterBeats, double pixels, int numerator, int denominator,
                                        double minimumLabelSpacingPixels = 72.0)
{
    const double beat = 4.0 / std::max(1, denominator);
    const double bar = beatsPerBar(numerator, denominator);
    if (!std::isfinite(visibleQuarterBeats) || !std::isfinite(pixels)) return { bar, 0 };
    const double spacing = std::isfinite(minimumLabelSpacingPixels) ? std::max(1.0, minimumLabelSpacingPixels) : 72.0;
    const double wanted = std::max(0.0, visibleQuarterBeats) * spacing / std::max(1.0, pixels);
    if (wanted <= beat * 0.25) return { beat * 0.25, 2 };
    if (wanted <= beat * 0.5) return { beat * 0.5, 2 };
    if (wanted <= beat) return { beat, 1 };
    return { bar * std::pow(2.0, std::ceil(std::log2(std::max(1.0, wanted / bar)) - 1.0e-10)), 0 };
}
inline std::string musicalRulerLabel(double quarterBeat, int numerator, int denominator, int tier)
{
    const double units = quarterBeat * std::max(1, denominator);
    if (!std::isfinite(units) || units < 0.0 || units > 9.0e15) return {};
    const auto subdivision = static_cast<std::int64_t>(std::llround(units));
    const auto barUnits = static_cast<std::int64_t>(std::max(1, numerator)) * 4;
    auto label = std::to_string(subdivision / barUnits + 1);
    if (tier >= 1) label += "." + std::to_string((subdivision % barUnits) / 4 + 1);
    if (tier >= 2) label += "." + std::to_string(subdivision % 4 + 1);
    return label;
}
}
