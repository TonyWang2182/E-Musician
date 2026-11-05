#pragma once

#include <array>
#include <cstddef>
#include <vector>

namespace emusician::effects {

// Independent stereo Schroeder network. Values form the host's public state
// contract; decay_seconds is the approximate broadband RT60 in seconds.
struct ReverbSettings {
    float decaySeconds = 1.8f;
    float damping = .35f;
    float dryWet = .25f;
};

bool valid(const ReverbSettings&) noexcept;

class StereoReverb final {
public:
    static constexpr double minimumSampleRate = 8000.0;
    static constexpr double maximumSampleRate = 384000.0;
    // 50 ms at 384 kHz plus one sample. Every line allocates once during
    // construction, never inside process() or reset().
    static constexpr std::size_t maximumLineFrames = 19201;
    StereoReverb();

    // In-place. Only the rendering thread may call process or reset. A null or
    // aliased right pointer denotes mono. A changed sample rate resets the
    // existing tail in O(number of delay lines), without touching the buffers.
    void process(float* left, float* right, int frames, double sampleRate, const ReverbSettings&) noexcept;
    void reset() noexcept;

private:
    struct Line {
        std::vector<float> data;
        std::size_t length = 1, cursor = 0, filled = 0;
        float filtered = 0;
        float read() const noexcept { return filled < length ? 0.0f : data[cursor]; }
        void write(float value) noexcept {
            data[cursor] = value;
            if (++cursor >= length) cursor = 0;
            if (filled < length) ++filled;
        }
        void reset() noexcept { cursor = filled = 0; filtered = 0; }
    };
    std::array<std::array<Line,6>,2> lines;
    double rate = 0;
    double currentMix = 0;
    float currentDamping=0;
    std::array<std::array<float,4>,2> currentFeedback{};
    bool mixInitialised = false;
    void configure(double sampleRate) noexcept;
};
} // namespace emusician::effects
