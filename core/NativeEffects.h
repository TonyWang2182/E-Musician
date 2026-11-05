#pragma once

#include <array>
#include <cstddef>
#include <vector>
#include <string_view>

// Allocation-free audio DSP. Parameters are immutable for one process call and
// supplied by the host as a coherent block snapshot, never a mutable UI model.
namespace emusician::effects {
inline constexpr std::size_t eqBandCount = 8;
enum class FilterShape { legacy, bell, lowShelf, highShelf, highPass, lowPass, notch };
// Missing shape in a version-1 project retains the original end shelves.
FilterShape effectiveShape(FilterShape, std::size_t band) noexcept;
const char* shapeName(FilterShape, std::size_t band = 1) noexcept;
bool parseShape(std::string_view, FilterShape&) noexcept;
struct Band { bool enabled = true; float frequency = 1000.0f, gainDb = 0.0f, q = 0.7071f; FilterShape shape = FilterShape::legacy; };
struct EqSettings {
    std::array<Band, eqBandCount> bands {{
        {true, 60, 0, .7071f}, {true, 120, 0, .7071f}, {true, 250, 0, .7071f},
        {true, 500, 0, .7071f}, {true, 1000, 0, .7071f}, {true, 2500, 0, .7071f},
        {true, 6000, 0, .7071f}, {true, 12000, 0, .7071f}}};
};
struct CompressorSettings {
    float thresholdDb = -18, ratio = 4, attackMs = 10, releaseMs = 100, makeupDb = 0, dryWet = 1;
};
struct DelaySettings { float delayMs = 350, feedback = .35f, dryWet = .35f; };
// Validation is for non-realtime command/state boundaries; callers must not
// publish invalid values. Limits intentionally match the UI/Agent contract.
bool valid(const EqSettings&) noexcept;
bool valid(const CompressorSettings&) noexcept;
bool valid(const DelaySettings&) noexcept;

double responseDb(double frequency, double sampleRate, const EqSettings&) noexcept;

class Equalizer final {
public:
    // In-place mono or stereo. Only the rendering thread may call this/reset.
    void process(float* left, float* right, int samples, double sampleRate, const EqSettings&) noexcept;
    void reset() noexcept;
private:
    friend double responseDb(double, double, const EqSettings&) noexcept;
    struct Coeff { double b0=1,b1=0,b2=0,a1=0,a2=0; };
    struct Delay { double z1=0,z2=0; };
    std::array<Coeff,eqBandCount> coefficients {};
    std::array<Coeff,eqBandCount> targets {}, increments {};
    std::array<int,eqBandCount> remaining {};
    std::array<std::array<Delay,2>,eqBandCount> delays {};
    EqSettings last {};
    double lastRate=0;
    void update(double, const EqSettings&) noexcept;
};
class Compressor final {
public:
    void process(float* left, float* right, int samples, double sampleRate, const CompressorSettings&) noexcept;
    void reset() noexcept { envelope = 0; reductionDb = 0; mixInitialised = false; }
    // Last processed block's instantaneous wet-path reduction, before makeup.
    // Owned by the rendering thread; host publishes a snapshot separately.
    float lastReductionDb() const noexcept { return reductionDb; }
private:
    double envelope = 0;
    float reductionDb = 0;
    double currentMix = 1;
    double currentAttack=0,currentRelease=0,currentThreshold=1,currentPower=0,currentMakeup=1;
    bool mixInitialised = false;
};
// Storage is allocated once during construction, outside the audio callback.
class StereoDelay final {
public:
    static constexpr std::size_t maxFrames = 768001;
    StereoDelay();
    void process(float* left, float* right, int samples, double sampleRate, const DelaySettings&) noexcept;
    void reset() noexcept { writeIndex = 0; validFrames = 0; mixInitialised = false; }
private:
    std::vector<float> historyLeft, historyRight;
    std::size_t writeIndex = 0, validFrames = 0;
    double currentMix = 0;
    double currentDelay=1,currentFeedback=0;
    bool mixInitialised = false;
};
} // namespace emusician::effects
