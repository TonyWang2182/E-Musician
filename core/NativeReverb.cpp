#include "core/NativeReverb.h"

#include <algorithm>
#include <cmath>
#include <limits>

namespace emusician::effects {
namespace {
constexpr std::array<double,6> delayMs {29.7, 37.1, 41.1, 43.7, 5.0, 1.7};
constexpr double spreadMs = .91;
constexpr float internalLimit = 64.0f;
bool between(float value,float low,float high) noexcept {
    return std::isfinite(value) && value >= low && value <= high;
}
float finiteInput(float value) noexcept { return std::isfinite(value) ? value : 0.0f; }
float bounded(float value) noexcept {
    return std::isfinite(value) && std::abs(value) >= 1e-20f ? std::clamp(value,-internalLimit,internalLimit) : 0.0f;
}
float output(double value) noexcept {
    if (!std::isfinite(value)) return 0.0f;
    constexpr auto limit = double(std::numeric_limits<float>::max());
    return float(std::clamp(value,-limit,limit));
}
}

bool valid(const ReverbSettings& value) noexcept {
    return between(value.decaySeconds,.1f,8.0f) && between(value.damping,0,1) && between(value.dryWet,0,1);
}

StereoReverb::StereoReverb() {
    for (auto& channel : lines) for (auto& line : channel) line.data.resize(maximumLineFrames);
}

void StereoReverb::reset() noexcept {
    for (auto& channel : lines) for (auto& line : channel) line.reset();
    mixInitialised = false;
}

void StereoReverb::configure(double sampleRate) noexcept {
    for (std::size_t channel=0;channel<lines.size();++channel)
        for (std::size_t i=0;i<lines[channel].size();++i) {
            const auto milliseconds = delayMs[i] + (channel ? spreadMs : 0.0);
            lines[channel][i].length = std::clamp<std::size_t>(
                std::size_t(std::llround(milliseconds * .001 * sampleRate)), 1, maximumLineFrames);
        }
    rate = sampleRate;
    reset();
}

void StereoReverb::process(float* left,float* right,int frames,double sampleRate,const ReverbSettings& settings) noexcept {
    if (!left || frames <= 0 || !std::isfinite(sampleRate) || sampleRate < minimumSampleRate
        || sampleRate > maximumSampleRate || !valid(settings)) return;
    if (right == left) right = nullptr;
    if (sampleRate != rate) configure(sampleRate);
    const bool first=!mixInitialised;
    if(first){currentMix=settings.dryWet;currentDamping=settings.damping*.95f;mixInitialised=true;}
    const double target = settings.dryWet, mixStep = 1.0 / (sampleRate * .005);
    const float damping = settings.damping * .95f;
    std::array<std::array<float,4>,2> feedback{};
    for (std::size_t channel=0;channel<2;++channel)
        for (std::size_t i=0;i<4;++i)
            feedback[channel][i] = float(std::exp(-6.907755278982137 * double(lines[channel][i].length)
                                                 / (sampleRate * settings.decaySeconds)));
    if(first)currentFeedback=feedback;
    const float smooth=float(1-std::exp(-1.0/(sampleRate*.02)));
    for (int frame=0;frame<frames;++frame) {
        currentDamping+=(damping-currentDamping)*smooth;
        const float dryL=finiteInput(left[frame]);
        const float dryR=right ? finiteInput(right[frame]) : dryL;
        const float safeL=bounded(dryL), safeR=bounded(dryR);
        const std::array<float,2> input{.8f*safeL+.2f*safeR, .8f*safeR+.2f*safeL};
        std::array<float,2> wet{};
        for (std::size_t channel=0;channel<(right?2u:1u);++channel) {
            float combined=0;
            for (std::size_t i=0;i<4;++i) {
                auto& line=lines[channel][i];
                const auto delayed=line.read();
                currentFeedback[channel][i]+=(feedback[channel][i]-currentFeedback[channel][i])*smooth;
                line.filtered=bounded((1-currentDamping)*delayed+currentDamping*line.filtered);
                if(std::abs(line.filtered)<1e-20f)line.filtered=0;
                line.write(bounded(input[channel]+currentFeedback[channel][i]*line.filtered));
                combined+=delayed*.25f;
            }
            for (std::size_t i=4;i<6;++i) {
                auto& line=lines[channel][i];
                const auto delayed=line.read();
                line.write(bounded(combined+.5f*delayed));
                combined=bounded(delayed-.5f*combined);
            }
            wet[channel]=combined;
        }
        currentMix+=std::clamp(target-currentMix,-mixStep,mixStep);
        left[frame]=output(double(dryL)*(1-currentMix)+double(wet[0])*currentMix);
        if(right)right[frame]=output(double(dryR)*(1-currentMix)+double(wet[1])*currentMix);
    }
}
} // namespace emusician::effects
