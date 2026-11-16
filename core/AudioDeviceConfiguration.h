#pragma once
#include <juce_core/juce_core.h>
#include <cmath>

namespace emusician::audio_config {
// Validate before opening any device. The actual device's channel count is
// checked separately after opening; a syntactically valid index is not a claim
// that a driver supports it.
inline juce::Result parseIndices(const juce::var& value, const juce::String& field,
                                 juce::BigInteger& result, bool stereoPairs = false)
{
    const auto* values = value.getArray();
    if (!values) return juce::Result::fail(field + " must be an array of channel indices.");
    result.clear();
    for (const auto& item : *values) {
        if ((!item.isInt() && !item.isInt64() && !item.isDouble())
            || !std::isfinite(double(item)) || double(item) != std::floor(double(item))
            || double(item) < 0 || double(item) > 1023)
            return juce::Result::fail(field + " must contain integer channel indices from 0 to 1023.");
        const int index = int(item);
        if (stereoPairs && index % 2 != 0)
            return juce::Result::fail("Stereo pairs must start at an even zero-based input channel index.");
        if (result[index]) return juce::Result::fail(field + " contains a duplicate channel index.");
        result.setBit(index);
    }
    return juce::Result::ok();
}
inline juce::Result validateAvailable(const juce::BigInteger& channels, int count)
{
    if (channels.getHighestBit() >= count)
        return juce::Result::fail("An input channel index is unavailable on the selected audio device.");
    return juce::Result::ok();
}
inline juce::BigInteger defaultInputs(int count)
{
    juce::BigInteger result;
    result.setRange(0, juce::jmin(2, count), true);
    return result;
}
inline juce::Array<juce::var> indices(const juce::BigInteger& channels)
{
    juce::Array<juce::var> result;
    for (int i = channels.findNextSetBit(0); i >= 0; i = channels.findNextSetBit(i + 1)) result.add(i);
    return result;
}
} // namespace emusician::audio_config
