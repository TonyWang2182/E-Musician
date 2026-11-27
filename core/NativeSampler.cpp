#include "NativeSampler.h"

#include <algorithm>
#include <cmath>
#include <limits>

namespace emusician::sampler {
namespace {
bool validSlot(const Slot& s) noexcept {
    return s.left != nullptr && s.frames > 0 && s.startFrame < s.endFrame
        && s.endFrame <= s.frames && std::isfinite(s.sampleRate) && s.sampleRate >= 1000
        && s.sampleRate <= 768000 && s.rootNote >= 0 && s.rootNote <= 127
        && s.minNote >= 0 && s.maxNote <= 127 && s.minNote <= s.maxNote
        && std::isfinite(s.gain) && s.gain >= 0 && s.gain <= 16
        && std::isfinite(s.attackSeconds) && s.attackSeconds >= 0 && s.attackSeconds <= 60
        && std::isfinite(s.releaseSeconds) && s.releaseSeconds >= 0 && s.releaseSeconds <= 60;
}
float increment(float seconds, double rate) noexcept {
    return seconds <= 0 ? 1.0f : static_cast<float>(std::min(1.0, 1.0 / (double(seconds) * rate)));
}
float sample(const float* data, std::size_t index, std::size_t end, double fraction) noexcept {
    const float rawA = data[index], rawB = data[std::min(index + 1, end - 1)];
    const float a = std::isfinite(rawA) ? rawA : 0.0f, b = std::isfinite(rawB) ? rawB : 0.0f;
    return a + (b - a) * static_cast<float>(fraction);
}
}

void Renderer::reset() noexcept {
    for (auto& voice : voices) voice.active = false;
    generationSeen = false;
}

void Renderer::handle(const Bank& bank, const Event& event, double rate) noexcept {
    if (event.channel < 1 || event.channel > 16) return;
    if (event.type == EventType::allNotesOff || event.type == EventType::allSoundOff) {
        for (auto& voice : voices)
            if (voice.active && voice.channel == event.channel) {
                if (event.type == EventType::allSoundOff) voice.active = false;
                else voice.releasing = true;
            }
        return;
    }
    if (event.note < 0 || event.note > 127 || !std::isfinite(event.velocity)) return;
    if (event.type == EventType::noteOff || (event.type == EventType::noteOn && event.velocity <= 0)) {
        for (auto& voice : voices)
            if (voice.active && !voice.oneShot && voice.channel == event.channel && voice.note == event.note)
                voice.releasing = true;
        return;
    }
    if (event.type != EventType::noteOn) return;
    for (std::size_t i = 0; i < bank.slots.size(); ++i) {
        const auto& slot = bank.slots[i];
        if (slot.muted || !validSlot(slot) || event.note < slot.minNote || event.note > slot.maxNote) continue;
        Voice* chosen = nullptr;
        for (auto& voice : voices) if (!voice.active) { chosen = &voice; break; }
        if (!chosen) chosen = &*std::min_element(voices.begin(), voices.end(),
            [](const Voice& a, const Voice& b) { return a.age < b.age; });
        *chosen = Voice {};
        chosen->active = true; chosen->oneShot = slot.oneShot;
        chosen->slot = static_cast<std::uint8_t>(i); chosen->channel = static_cast<std::uint8_t>(event.channel);
        chosen->note = static_cast<std::uint8_t>(event.note); chosen->age = nextAge++;
        chosen->position = static_cast<double>(slot.startFrame);
        chosen->step = (slot.sampleRate / rate) * std::exp2(double(event.note - slot.rootNote) / 12.0);
        chosen->gain = slot.gain * std::clamp(event.velocity, 0.0f, 1.0f);
        chosen->attackStep = increment(slot.attackSeconds, rate);
        chosen->releaseStep = increment(slot.releaseSeconds, rate);
    }
}

void Renderer::process(const Bank& bank, float* left, float* right, int n,
                       const Event* events, int count, double rate) noexcept {
    if (!left || n <= 0 || !std::isfinite(rate) || rate < 1000 || rate > 768000) return;
    if (!generationSeen || generation != bank.generation || currentRate != rate) {
        for (auto& voice : voices) voice.active = false;
        generation = bank.generation; generationSeen = true; currentRate = rate;
    }
    if (!events || count < 0) count = 0;
    count = std::min(count, maxEventsPerBlock);
    int eventIndex = 0;
    for (int frame = 0; frame < n; ++frame) {
        while (eventIndex < count && events[eventIndex].offset <= frame) {
            if (events[eventIndex].offset >= 0) handle(bank, events[eventIndex], rate);
            ++eventIndex;
        }
        for (auto& voice : voices) {
            if (!voice.active) continue;
            const auto& slot = bank.slots[voice.slot];
            // Configuration is immutable while this generation is published.
            if (voice.position >= static_cast<double>(slot.endFrame)) {
                voice.active = false; continue;
            }
            if (voice.releasing) {
                voice.envelope = std::max(0.0f, voice.envelope - voice.releaseStep);
                if (voice.envelope <= 0) { voice.active = false; continue; }
            } else {
                voice.envelope = std::min(1.0f, voice.envelope + voice.attackStep);
            }
            const auto index = static_cast<std::size_t>(voice.position);
            const auto fraction = voice.position - static_cast<double>(index);
            const auto tail = static_cast<float>(std::clamp((static_cast<double>(slot.endFrame) - voice.position)
                                                            / (voice.step * 16.0), 0.0, 1.0));
            const float scale = voice.gain * voice.envelope * tail;
            left[frame] += sample(slot.left, index, slot.endFrame, fraction) * scale;
            if (right && right != left) right[frame] += sample(slot.right ? slot.right : slot.left, index, slot.endFrame, fraction) * scale;
            voice.position += voice.step;
        }
    }
}
} // namespace emusician::sampler
