#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

// Non-owning, bounded sample renderer. Host code owns loading, publication,
// sample lifetimes and MIDI decoding. No JUCE, locks or allocation in process().
namespace emusician::sampler {

inline constexpr std::size_t maxSlots = 16;
inline constexpr std::size_t maxVoices = 64;
inline constexpr int maxEventsPerBlock = 4096;

struct Slot {
    // Deinterleaved samples; null right aliases left. Pointers and contents
    // must stay valid and immutable throughout every callback that uses them.
    const float* left = nullptr;
    const float* right = nullptr;
    std::size_t frames = 0, startFrame = 0, endFrame = 0; // end exclusive
    double sampleRate = 0;
    int rootNote = 60, minNote = 0, maxNote = 127;
    float gain = 1.0f;
    float attackSeconds = 0.003f, releaseSeconds = 0.030f;
    bool muted = false, oneShot = false;
};

struct Bank {
    std::array<Slot, maxSlots> slots {};
    // Increment whenever sample memory or slot configuration changes. All
    // voices stop at the next block boundary, before new pointers are read.
    std::uint64_t generation = 0;
};

enum class EventType : std::uint8_t { noteOn, noteOff, allNotesOff, allSoundOff };
struct Event {
    int offset = 0; // samples from block start; nondecreasing and [0, n)
    EventType type = EventType::noteOn;
    int channel = 1, note = 60; // MIDI channels 1..16 and notes 0..127
    float velocity = 1.0f;      // normalized 0..1, zero note-on = note-off
};

class Renderer final {
public:
    // Adds into caller-owned output; null right renders mono. Events must be
    // sorted by offset and count <= maxEventsPerBlock. Excess events and
    // invalid events/slots are ignored. This function must
    // be called by one audio thread only. No bank reference is retained.
    // The host MUST retire old bank/sample memory only after every callback
    // using it has returned, and must retire/free it outside the audio thread.
    void process(const Bank&, float* left, float* right, int samples,
                 const Event* events, int eventCount, double outputRate) noexcept;
    void reset() noexcept;

private:
    struct Voice {
        bool active = false, releasing = false, oneShot = false;
        std::uint8_t slot = 0, channel = 0, note = 0;
        std::uint64_t age = 0;
        double position = 0, step = 0;
        float envelope = 0, attackStep = 1, releaseStep = 1, gain = 0;
    };
    std::array<Voice, maxVoices> voices {};
    std::uint64_t generation = 0, nextAge = 0;
    double currentRate = 0;
    bool generationSeen = false;
    void handle(const Bank&, const Event&, double outputRate) noexcept;
};

} // namespace emusician::sampler
