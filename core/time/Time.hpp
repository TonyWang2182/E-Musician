#pragma once

#include <cmath>
#include <cstdint>
#include <stdexcept>

namespace emusician::time {

namespace detail {

inline void validatePosition(double position)
{
    if (!std::isfinite(position) || position < 0.0)
        throw std::invalid_argument("Time position must be finite and non-negative");
}

inline void validateRate(double rate)
{
    if (!std::isfinite(rate) || rate <= 0.0)
        throw std::invalid_argument("Time rate must be finite and positive");
}

// Scaling the operands avoids spurious intermediate overflow/underflow.
// This also works on MSVC, where long double has the same range as double.
inline double checkedMultiplyDivide(double position, double multiplier, double divisor)
{
    if (position == 0.0)
        return 0.0;

    int positionExponent = 0;
    int multiplierExponent = 0;
    int divisorExponent = 0;
    const double positionMantissa = std::frexp(position, &positionExponent);
    const double multiplierMantissa = std::frexp(multiplier, &multiplierExponent);
    const double divisorMantissa = std::frexp(divisor, &divisorExponent);
    const double mantissa = positionMantissa * multiplierMantissa / divisorMantissa;
    const double result = std::scalbn(
        mantissa, positionExponent + multiplierExponent - divisorExponent);

    if (!std::isfinite(result))
        throw std::overflow_error("Converted time exceeds double range");
    return result;
}

} // namespace detail

// Positions are non-negative; the tempo is constant for this conversion.
inline double secondsToBeats(double seconds, double bpm)
{
    detail::validatePosition(seconds);
    detail::validateRate(bpm);
    return detail::checkedMultiplyDivide(seconds, bpm, 60.0);
}

inline double beatsToSeconds(double beats, double bpm)
{
    detail::validatePosition(beats);
    detail::validateRate(bpm);
    return detail::checkedMultiplyDivide(beats, 60.0, bpm);
}

// Round to the nearest sample; half-sample ties round upward.
inline std::int64_t secondsToSamples(double seconds, double sampleRate)
{
    detail::validatePosition(seconds);
    detail::validateRate(sampleRate);
    const double samples = detail::checkedMultiplyDivide(seconds, sampleRate, 1.0);
    const double rounded = std::round(samples);

    // double(INT64_MAX) rounds to 2^63, so it is not a safe inclusive limit.
    constexpr double exclusiveUpperBound = 0x1p63;
    if (rounded >= exclusiveUpperBound)
        throw std::overflow_error("Sample position exceeds int64 range");
    return static_cast<std::int64_t>(rounded);
}

} // namespace emusician::time