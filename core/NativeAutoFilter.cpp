#include "NativeAutoFilter.h"
#include <algorithm>
#include <cmath>
#include <limits>
#include <numbers>

namespace emusician::autofilter {
namespace {
bool between(float x,float lo,float hi) noexcept {return std::isfinite(x)&&x>=lo&&x<=hi;}
}
bool valid(const Settings& s) noexcept {
    return (s.mode==Mode::lowPass||s.mode==Mode::highPass)
        && between(s.frequencyHz,20,20000) && between(s.resonanceQ,.5f,10)
        && between(s.lfoHz,.05f,20) && between(s.lfoDepth,0,1) && between(s.dryWet,0,1);
}
void Filter::reset() noexcept {
    channels[0]={};channels[1]={};sampleRate=0;phase=0;untilUpdate=0;initialised=false;
}
void Filter::updateCoefficients(double hz,double q,Mode mode) noexcept {
    const double w=2*std::numbers::pi*hz/sampleRate, sn=std::sin(w), cs=std::cos(w);
    const double alpha=sn/(2*q), a0=1+alpha;
    if(mode==Mode::lowPass){b0=(1-cs)*.5/a0;b1=(1-cs)/a0;b2=b0;}
    else {b0=(1+cs)*.5/a0;b1=-(1+cs)/a0;b2=b0;}
    a1=(-2*cs)/a0;a2=(1-alpha)/a0;
}
void Filter::process(float* left,float* right,int frames,double rate,const Settings& settings) noexcept {
    if(!left||frames<=0||!std::isfinite(rate)||rate<1000||rate>384000||!valid(settings))return;
    if(right==left)right=nullptr;
    if(sampleRate!=rate){channels[0]={};channels[1]={};sampleRate=rate;untilUpdate=0;initialised=false;}
    if(!initialised){frequency=settings.frequencyHz;resonance=settings.resonanceQ;mix=settings.dryWet;depth=settings.lfoEnabled?settings.lfoDepth:0;lfoRate=settings.lfoHz;currentMode=settings.mode;initialised=true;}
    const double smooth=1-std::exp(-16.0/(rate*.01));
    const double mixStep=1.0/(rate*.005);
    constexpr auto maximum=double(std::numeric_limits<float>::max());
    for(int i=0;i<frames;++i){
        if(untilUpdate==0){
            frequency+=(double(settings.frequencyHz)-frequency)*smooth;
            resonance+=(double(settings.resonanceQ)-resonance)*smooth;
            lfoRate+=(double(settings.lfoHz)-lfoRate)*smooth;
            depth+=((settings.lfoEnabled?double(settings.lfoDepth):0.0)-depth)*smooth;
            // Mode changes are explicit and coefficients update at most 16 samples later.
            currentMode=settings.mode;
            const double modulation=std::exp2(2.0*depth*std::sin(phase));
            updateCoefficients(std::clamp(frequency*modulation,20.0,rate*.45),resonance,currentMode);
            untilUpdate=16;
        }
        --untilUpdate;
        mix+=std::clamp(double(settings.dryWet)-mix,-mixStep,mixStep);
        for(int c=0;c<(right?2:1);++c){
            float* buffer=c?right:left;auto& state=channels[c];
            const double input=std::isfinite(buffer[i])?double(buffer[i]):0.0;
            const double filtered=b0*input+state.z1;
            state.z1=b1*input-a1*filtered+state.z2;state.z2=b2*input-a2*filtered;
            if(!std::isfinite(filtered)||!std::isfinite(state.z1)||!std::isfinite(state.z2)){state={};buffer[i]=0;}
            else buffer[i]=float(std::clamp(input*(1-mix)+filtered*mix,-maximum,maximum));
        }
        phase+=2*std::numbers::pi*lfoRate/rate;if(phase>=2*std::numbers::pi)phase-=2*std::numbers::pi;
    }
    for(auto& c:channels){if(std::abs(c.z1)<1e-20)c.z1=0;if(std::abs(c.z2)<1e-20)c.z2=0;}
}
} // namespace emusician::autofilter
