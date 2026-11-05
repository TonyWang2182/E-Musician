#pragma once

namespace emusician::autofilter {
enum class Mode { lowPass, highPass };
struct Settings {
    Mode mode = Mode::lowPass;
    float frequencyHz = 1000.0f;
    float resonanceQ = .7071f;
    bool lfoEnabled = false;
    float lfoHz = 1.0f;
    float lfoDepth = 0.0f; // 0..1, up to +/- two octaves
    float dryWet = 1.0f;
};
bool valid(const Settings&) noexcept;

// Bounded, allocation-free biquad. One instance belongs to one render thread.
// Parameters remain immutable throughout the process call; no networking,
// file access, locking or memory allocation is performed in the callback.
class Filter final {
public:
    void process(float* left, float* right, int frames, double sampleRate, const Settings&) noexcept;
    void reset() noexcept;
private:
    struct Channel { double z1 = 0, z2 = 0; };
    Channel channels[2];
    double b0 = 1, b1 = 0, b2 = 0, a1 = 0, a2 = 0;
    double sampleRate = 0, phase = 0, frequency = 1000, resonance = .7071, mix = 1, depth = 0, lfoRate = 1;
    unsigned untilUpdate = 0;
    Mode currentMode = Mode::lowPass;
    bool initialised = false;
    void updateCoefficients(double hz, double q, Mode mode) noexcept;
};
} // namespace emusician::autofilter
