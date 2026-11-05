#include "core/NativeEffects.h"
#include <algorithm>
#include <cmath>
#include <numbers>
#include <limits>
#include <complex>

namespace emusician::effects {
namespace {
bool between(float v, float lo, float hi) noexcept { return std::isfinite(v) && v >= lo && v <= hi; }
bool gainShape(FilterShape s) noexcept { return s == FilterShape::bell || s == FilterShape::lowShelf || s == FilterShape::highShelf; }
}
FilterShape effectiveShape(FilterShape s, std::size_t band) noexcept {
    return s != FilterShape::legacy ? s : band == 0 ? FilterShape::lowShelf : band == eqBandCount - 1 ? FilterShape::highShelf : FilterShape::bell;
}
const char* shapeName(FilterShape s, std::size_t band) noexcept {
    switch (effectiveShape(s, band)) {
        case FilterShape::lowShelf: return "low_shelf";
        case FilterShape::highShelf: return "high_shelf";
        case FilterShape::highPass: return "high_pass";
        case FilterShape::lowPass: return "low_pass";
        case FilterShape::notch: return "notch";
        default: return "bell";
    }
}
bool parseShape(std::string_view name, FilterShape& out) noexcept {
    for (auto s : {FilterShape::bell, FilterShape::lowShelf, FilterShape::highShelf, FilterShape::highPass, FilterShape::lowPass, FilterShape::notch})
        if (name == shapeName(s)) { out = s; return true; }
    return false;
}
bool valid(const EqSettings& s) noexcept {
    for (const auto& b : s.bands)
        if (!between(b.frequency,20,20000) || !between(b.gainDb,-24,24) || !between(b.q,.1f,10)
            || b.shape < FilterShape::legacy || b.shape > FilterShape::notch) return false;
    return true;
}
bool valid(const CompressorSettings& s) noexcept {
    return between(s.thresholdDb,-60,0) && between(s.ratio,1,20) && between(s.attackMs,.1f,200)
        && between(s.releaseMs,10,2000) && between(s.makeupDb,-24,24) && between(s.dryWet,0,1);
}
bool valid(const DelaySettings& s) noexcept {
    return between(s.delayMs,1,2000) && between(s.feedback,0,.95f) && between(s.dryWet,0,1);
}
void Equalizer::reset() noexcept { delays = {}; }
void Equalizer::update(double sr, const EqSettings& settings) noexcept {
    for (std::size_t i=0;i<eqBandCount;++i) {
        const auto& b=settings.bands[i]; auto& c=coefficients[i];
        const auto shape = effectiveShape(b.shape, i);
        if (!b.enabled || (b.gainDb == 0 && gainShape(shape))) { c={}; continue; }
        const auto f=std::min(double(b.frequency),sr*.475);
        const auto w=2*std::numbers::pi*f/sr, sn=std::sin(w), cs=std::cos(w);
        const auto A=std::pow(10.0,double(b.gainDb)/40.0);
        const auto alpha=sn/(2*double(b.q));
        double b0,b1,b2,a0,a1,a2;
        if (shape == FilterShape::lowShelf || shape == FilterShape::highShelf) {
            // RBJ shelving filters. Q controls the width via alpha.
            const auto beta=2*std::sqrt(A)*alpha;
            if (shape == FilterShape::lowShelf) {
                b0=A*((A+1)-(A-1)*cs+beta); b1=2*A*((A-1)-(A+1)*cs); b2=A*((A+1)-(A-1)*cs-beta);
                a0=(A+1)+(A-1)*cs+beta; a1=-2*((A-1)+(A+1)*cs); a2=(A+1)+(A-1)*cs-beta;
            } else {
                b0=A*((A+1)+(A-1)*cs+beta); b1=-2*A*((A-1)+(A+1)*cs); b2=A*((A+1)+(A-1)*cs-beta);
                a0=(A+1)-(A-1)*cs+beta; a1=2*((A-1)-(A+1)*cs); a2=(A+1)-(A-1)*cs-beta;
            }
        } else if (shape == FilterShape::highPass || shape == FilterShape::lowPass || shape == FilterShape::notch) {
            a0=1+alpha; a1=-2*cs; a2=1-alpha;
            if (shape == FilterShape::highPass) { b0=(1+cs)*.5; b1=-(1+cs); b2=b0; }
            else if (shape == FilterShape::lowPass) { b0=(1-cs)*.5; b1=1-cs; b2=b0; }
            else { b0=1; b1=-2*cs; b2=1; }
        } else {
            b0=1+alpha*A; b1=-2*cs; b2=1-alpha*A;
            a0=1+alpha/A; a1=-2*cs; a2=1-alpha/A;
        }
        c={b0/a0,b1/a0,b2/a0,a1/a0,a2/a0};
    }
    last=settings; lastRate=sr;
}
void Equalizer::process(float* left,float* right,int n,double sr,const EqSettings& settings) noexcept {
    if (!left || n<=0 || !std::isfinite(sr) || sr<1000 || !valid(settings)) return;
    if(right==left)right=nullptr;
    for(int i=0;i<n;++i){if(!std::isfinite(left[i]))left[i]=0;if(right&&!std::isfinite(right[i]))right[i]=0;}
    bool changed=sr!=lastRate;
    for(std::size_t i=0;i<eqBandCount&&!changed;++i) {
        const auto& a=settings.bands[i];const auto& b=last.bands[i];
        changed=a.enabled!=b.enabled || a.frequency!=b.frequency || a.gainDb!=b.gainDb || a.q!=b.q || a.shape!=b.shape;
    }
    if(changed) update(sr,settings);
    for(std::size_t band=0;band<eqBandCount;++band) {
        if(!settings.bands[band].enabled || (settings.bands[band].gainDb==0 && gainShape(effectiveShape(settings.bands[band].shape,band)))) { delays[band]={}; continue; }
        const auto c=coefficients[band];
        for(int channel=0;channel<(right?2:1);++channel) {
            auto* buffer=channel?right:left;auto& d=delays[band][std::size_t(channel)];
            for(int i=0;i<n;++i) {
                const auto x=double(buffer[i]); const auto y=c.b0*x+d.z1;
                d.z1=c.b1*x-c.a1*y+d.z2; d.z2=c.b2*x-c.a2*y;
                if(!std::isfinite(y) || std::abs(y)>double(std::numeric_limits<float>::max())){d={};buffer[i]=0;}
                else buffer[i]=float(y);
            }
            // Avoid costly denormal tails without altering normal signals.
            if(std::abs(d.z1)<1e-20)d.z1=0;
            if(std::abs(d.z2)<1e-20)d.z2=0;
        }
    }
}
double responseDb(double frequency,double sr,const EqSettings& settings) noexcept {
    if(!std::isfinite(frequency)||!std::isfinite(sr)||sr<1000||frequency<0||frequency>sr*.5||!valid(settings))return 0;
    Equalizer eq;eq.update(sr,settings);
    const auto z=std::polar(1.0,-2*std::numbers::pi*frequency/sr),z2=z*z;
    std::complex<double> response=1;
    for(const auto& c:eq.coefficients)response*=(c.b0+c.b1*z+c.b2*z2)/(1.0+c.a1*z+c.a2*z2);
    return 20*std::log10(std::max(1.0e-12,std::abs(response)));
}
void Compressor::process(float* left,float* right,int n,double sr,const CompressorSettings& s) noexcept {
    if(!left || n<=0 || !std::isfinite(sr) || sr<1000 || !valid(s))return;
    if(right==left)right=nullptr;
    const auto attack=std::exp(-1.0/(sr*s.attackMs*.001));
    const auto release=std::exp(-1.0/(sr*s.releaseMs*.001));
    const auto threshold=std::pow(10.0,double(s.thresholdDb)/20.0);
    const auto power=1.0-1.0/double(s.ratio);
    const auto makeup=std::pow(10.0,double(s.makeupDb)/20.0);
    if(!mixInitialised){currentMix=s.dryWet;mixInitialised=true;}
    const auto targetMix=double(s.dryWet);
    const auto mixStep=1.0/(sr*.005); // bounded five-millisecond transition
    for(int i=0;i<n;++i) {
        if(!std::isfinite(left[i]))left[i]=0;
        if(right&&!std::isfinite(right[i]))right[i]=0;
        const auto level=std::max(std::abs(double(left[i])),right?std::abs(double(right[i])):0.0);
        const auto coeff=level>envelope?attack:release;
        envelope=coeff*envelope+(1-coeff)*level;
        const auto wetGain=(envelope>threshold?std::pow(threshold/envelope,power):1.0)*makeup;
        currentMix+=std::clamp(targetMix-currentMix,-mixStep,mixStep);
        const auto gain=(1.0-currentMix)+currentMix*wetGain;
        const auto limit=double(std::numeric_limits<float>::max());
        left[i]=float(std::clamp(double(left[i])*gain,-limit,limit));
        if(right)right[i]=float(std::clamp(double(right[i])*gain,-limit,limit));
    }
    const auto reduction=envelope>threshold?power*20.0*std::log10(envelope/threshold):0.0;
    reductionDb=float(std::clamp(reduction,0.0,120.0));
    if(envelope<1e-20)envelope=0;
}
StereoDelay::StereoDelay():historyLeft(maxFrames,0),historyRight(maxFrames,0) {}
void StereoDelay::process(float* left,float* right,int n,double sr,const DelaySettings& s) noexcept {
    if(!left||n<=0||!std::isfinite(sr)||sr<1000||sr>384000||!valid(s))return;
    if(right==left)right=nullptr;
    const auto delay=std::clamp<std::size_t>(std::size_t(std::llround(sr*double(s.delayMs)*.001)),1,maxFrames-1);
    if(!mixInitialised){currentMix=s.dryWet;mixInitialised=true;}
    const auto target=double(s.dryWet),step=1.0/(sr*.005);
    const auto limit=double(std::numeric_limits<float>::max());
    for(int i=0;i<n;++i){
        const auto inL=std::isfinite(left[i])?double(left[i]):0.0;
        const auto inR=right?(std::isfinite(right[i])?double(right[i]):0.0):inL;
        const auto read=(writeIndex+maxFrames-delay)%maxFrames;
        const double wetL=validFrames>=delay?historyLeft[read]:0.0;
        const double wetR=validFrames>=delay?historyRight[read]:0.0;
        historyLeft[writeIndex]=float(std::clamp(inL+wetL*s.feedback,-limit,limit));
        historyRight[writeIndex]=float(std::clamp(inR+wetR*s.feedback,-limit,limit));
        writeIndex=(writeIndex+1)%maxFrames;validFrames=std::min(validFrames+1,maxFrames);
        currentMix+=std::clamp(target-currentMix,-step,step);
        left[i]=float(std::clamp(inL*(1-currentMix)+wetL*currentMix,-limit,limit));
        if(right)right[i]=float(std::clamp(inR*(1-currentMix)+wetR*currentMix,-limit,limit));
    }
}
} // namespace emusician::effects
