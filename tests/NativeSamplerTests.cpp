#include "core/NativeSampler.h"

#include <array>
#include <atomic>
#include <cmath>
#include <cstdlib>
#include <iostream>
#include <limits>
#include <new>

namespace {
std::atomic<bool> countAllocations {false};
std::atomic<unsigned> allocationCount {0};
}
void* operator new(std::size_t bytes) {
    if (countAllocations.load(std::memory_order_relaxed)) allocationCount.fetch_add(1, std::memory_order_relaxed);
    if (auto* p = std::malloc(bytes ? bytes : 1)) return p;
    throw std::bad_alloc();
}
void* operator new[](std::size_t bytes) { return ::operator new(bytes); }
void operator delete(void* p) noexcept { std::free(p); }
void operator delete[](void* p) noexcept { std::free(p); }
void operator delete(void* p, std::size_t) noexcept { std::free(p); }
void operator delete[](void* p, std::size_t) noexcept { std::free(p); }

using namespace emusician::sampler;

namespace {
int failures = 0;
void check(bool condition, const char* name) {
    if (!condition) { std::cerr << "FAIL: " << name << '\n'; ++failures; }
}
bool near(float a, float b) { return std::abs(a - b) < 0.0001f; }
Slot slot(const float* data, std::size_t n) {
    Slot s; s.left = data; s.frames = n; s.endFrame = n; s.sampleRate = 48000;
    s.attackSeconds = 0; s.releaseSeconds = 0; return s;
}
}

int main() {
    std::array<float, 512> ones, halves;
    ones.fill(1); halves.fill(0.5f);
    std::array<float, 64> left {}, right {};
    Bank bank; bank.slots[0] = slot(ones.data(), ones.size());
    Renderer renderer;
    const Event on { 4, EventType::noteOn, 1, 60, 0.5f };
    renderer.process(bank, left.data(), right.data(), 16, &on, 1, 48000);
    check(near(left[3], 0) && near(left[4], 0.5f) && near(right[4], 0.5f), "sample-accurate note on, velocity and mono duplication");
    left.fill(0); right.fill(0);
    const Event off { 3, EventType::noteOff, 1, 60, 0 };
    renderer.process(bank, left.data(), right.data(), 16, &off, 1, 48000);
    check(near(left[2], 0.5f) && near(left[3], 0), "note off stops gated voice at event offset");

    renderer.reset(); ++bank.generation; bank.slots[0].right = halves.data(); bank.slots[0].oneShot = true;
    left.fill(0); right.fill(0);
    const std::array<Event, 2> oneShot {{ {0, EventType::noteOn, 1, 60, 1}, {2, EventType::noteOff, 1, 60, 0} }};
    renderer.process(bank, left.data(), right.data(), 16, oneShot.data(), int(oneShot.size()), 48000);
    check(near(left[5], 1) && near(right[5], 0.5f), "one shot ignores note off and preserves stereo");
    left.fill(0); right.fill(0); ++bank.generation;
    renderer.process(bank, left.data(), right.data(), 16, nullptr, 0, 48000);
    check(near(left[0], 0), "generation change stops old sample voices");

    renderer.reset(); bank = {}; bank.slots[0] = slot(ones.data(), ones.size());
    bank.slots[0].minNote = bank.slots[0].maxNote = bank.slots[0].rootNote = 36;
    bank.slots[1] = slot(halves.data(), halves.size()); bank.slots[1].minNote = bank.slots[1].maxNote = bank.slots[1].rootNote = 37;
    left.fill(0); right.fill(0);
    const std::array<Event, 2> pads {{ {0, EventType::noteOn, 1, 36, 1}, {1, EventType::noteOn, 1, 37, 1} }};
    renderer.process(bank, left.data(), right.data(), 16, pads.data(), int(pads.size()), 48000);
    check(near(left[0], 1) && near(left[1], 1.5f), "pad note mappings are independent and mix");
    bank.slots[1].muted = true; ++bank.generation; left.fill(0);
    renderer.process(bank, left.data(), nullptr, 16, pads.data(), int(pads.size()), 48000);
    check(near(left[1], 1), "muted pad is silent");

    renderer.reset(); bank = {};
    std::array<float, 256> ramp {};
    for (std::size_t i = 0; i < ramp.size(); ++i) ramp[i] = static_cast<float>(i) / 256;
    bank.slots[0] = slot(ramp.data(), ramp.size()); bank.slots[0].sampleRate = 24000;
    left.fill(0);
    const Event rootOn {0, EventType::noteOn, 1, 60, 1};
    renderer.process(bank, left.data(), nullptr, 16, &rootOn, 1, 48000);
    check(near(left[1], 0.5f / 256) && near(left[2], 1.0f / 256), "sample-rate conversion uses interpolation");
    renderer.reset(); left.fill(0);
    const Event octaveOn {0, EventType::noteOn, 1, 72, 1};
    renderer.process(bank, left.data(), nullptr, 16, &octaveOn, 1, 48000);
    check(near(left[1], 1.0f / 256) && near(left[2], 2.0f / 256), "one octave doubles playback rate");

    renderer.reset(); bank.slots[0].startFrame = 20; bank.slots[0].endFrame = 10; ++bank.generation; left.fill(0);
    renderer.process(bank, left.data(), nullptr, 16, &rootOn, 1, 48000);
    check(near(left[0], 0), "invalid excerpt fails silent");

    renderer.reset(); bank = {}; bank.slots[0] = slot(ones.data(), ones.size());
    std::array<Event, 65> poly {};
    for (auto& event : poly) event = {0, EventType::noteOn, 1, 60, 1};
    left.fill(0);
    renderer.process(bank, left.data(), nullptr, 1, poly.data(), int(poly.size()), 48000);
    check(near(left[0], float(maxVoices)), "voice count is bounded with deterministic oldest voice stealing");
    const Event wrongChannelOff {0, EventType::noteOff, 2, 60, 0};
    left.fill(0); renderer.process(bank, left.data(), nullptr, 1, &wrongChannelOff, 1, 48000);
    check(near(left[0], float(maxVoices)), "note off on another channel does not affect voices");
    const Event panic {0, EventType::allNotesOff, 1, 0, 0};
    left.fill(0); renderer.process(bank, left.data(), nullptr, 1, &panic, 1, 48000);
    check(near(left[0], 0), "all notes off releases one channel");

    renderer.reset(); bank = {}; bank.slots[0] = slot(ones.data(), ones.size());
    bank.slots[0].attackSeconds = 4.0f / 48000.0f;
    bank.slots[0].releaseSeconds = 4.0f / 48000.0f;
    left.fill(0); renderer.process(bank, left.data(), nullptr, 8, &rootOn, 1, 48000);
    check(near(left[0], .25f) && near(left[3], 1.0f), "attack reaches unity over specified frames");
    const Event release {0, EventType::noteOff, 1, 60, 0};
    left.fill(0); renderer.process(bank, left.data(), nullptr, 8, &release, 1, 48000);
    check(near(left[0], .75f) && near(left[3], 0), "release attenuates and ends voice");

    renderer.reset(); bank.slots[0].attackSeconds = 0; bank.slots[0].releaseSeconds = 1;
    const std::array<Event, 2> twoChannels {{ {0, EventType::noteOn, 1, 60, 1}, {0, EventType::noteOn, 2, 60, 1} }};
    left.fill(0); renderer.process(bank, left.data(), nullptr, 1, twoChannels.data(), int(twoChannels.size()), 48000);
    const Event channelKill {0, EventType::allSoundOff, 1, 0, 0};
    left.fill(0); renderer.process(bank, left.data(), nullptr, 1, &channelKill, 1, 48000);
    check(near(left[0], 1.0f), "all sound off cuts only its channel immediately regardless of release");

    renderer.reset(); bank = {}; bank.slots[0] = slot(ones.data(), ones.size());
    bank.slots[0].startFrame = 511; bank.slots[0].endFrame = 512; left.fill(0);
    renderer.process(bank, left.data(), nullptr, 8, &rootOn, 1, 48000);
    check(left[0] > 0 && near(left[1], 0), "one-frame excerpt ends without reading beyond final sample");

    renderer.reset(); std::array<float, 32> broken {}; broken.fill(std::numeric_limits<float>::quiet_NaN());
    bank = {}; bank.slots[0] = slot(broken.data(), broken.size()); left.fill(0);
    renderer.process(bank, left.data(), nullptr, 8, &rootOn, 1, 48000);
    check(std::isfinite(left[0]) && near(left[0], 0), "non-finite media does not poison audio output");
    renderer.reset(); bank = {}; bank.slots[0] = slot(ones.data(), ones.size()); left.fill(0);
    renderer.process(bank, left.data(), nullptr, 8, &rootOn, 1, 48000);
    left.fill(0); renderer.process(bank, left.data(), nullptr, 8, nullptr, 0, 44100);
    check(near(left[0], 0), "device rate change clears stale voice step");

    renderer.reset(); bank = {}; bank.slots[0] = slot(ones.data(), ones.size()); left.fill(0);
    allocationCount.store(0, std::memory_order_relaxed);
    countAllocations.store(true, std::memory_order_relaxed);
    renderer.process(bank, left.data(), nullptr, 16, poly.data(), int(poly.size()), 48000);
    countAllocations.store(false, std::memory_order_relaxed);
    check(allocationCount.load(std::memory_order_relaxed) == 0, "voice start, stealing and rendering do not allocate");
    if (failures == 0) std::cout << "PASS: native bounded sampler DSP\n";
    return failures == 0 ? 0 : 1;
}
