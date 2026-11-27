#include "core/NativeReverb.h"

#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstdlib>
#include <iostream>
#include <limits>
#include <new>
#include <vector>

namespace { std::atomic<bool> observe {false}; std::atomic<unsigned> allocations {0}; }
void* operator new(std::size_t n) { if(observe.load()) ++allocations; if(auto* p=std::malloc(n?n:1)) return p; throw std::bad_alloc(); }
void* operator new[](std::size_t n) { return ::operator new(n); }
void operator delete(void* p) noexcept { std::free(p); }
void operator delete[](void* p) noexcept { std::free(p); }
void operator delete(void* p,std::size_t) noexcept { std::free(p); }
void operator delete[](void* p,std::size_t) noexcept { std::free(p); }

using namespace emusician::effects;
namespace {
int failures=0;
void check(bool ok,const char* label) { if(!ok) { std::cerr << "FAIL: " << label << '\n'; ++failures; } }
double energy(const std::vector<float>& signal,std::size_t begin,std::size_t end) {
    double total=0;for(std::size_t i=begin;i<std::min(end,signal.size());++i)total+=double(signal[i])*signal[i];return total;
}
bool finite(const std::vector<float>& signal) { return std::all_of(signal.begin(),signal.end(),[](float x){return std::isfinite(x);}); }
void impulse(std::vector<float>& a,std::vector<float>& b) { std::fill(a.begin(),a.end(),0);std::fill(b.begin(),b.end(),0);a[0]=1;b[0]=1; }
}

int main() {
    constexpr int rate=48000, frames=rate*2;
    std::vector<float> l(frames),r(frames),shortTail(frames),unused(frames);
    ReverbSettings state;
    check(valid(state),"default parameters valid");
    auto invalid=state;invalid.decaySeconds=0;check(!valid(invalid),"zero decay rejected");
    invalid=state;invalid.damping=std::numeric_limits<float>::quiet_NaN();check(!valid(invalid),"nonfinite damping rejected");
    invalid=state;invalid.dryWet=1.01f;check(!valid(invalid),"wet outside bounds rejected");

    StereoReverb effect;
    impulse(l,r);state.dryWet=0;effect.process(l.data(),r.data(),frames,rate,state);
    check(l[0]==1 && r[0]==1 && energy(l,1,l.size())==0,"dry output preserves impulse exactly");
    effect.reset();impulse(l,r);state.dryWet=1;state.decaySeconds=3;state.damping=.2f;
    effect.process(l.data(),r.data(),frames,rate,state);
    check(l[0]==0 && energy(l,rate/20,rate/2)>1e-7,"fully wet network produces a delayed tail");
    double difference=0;for(std::size_t i=0;i<l.size();++i)difference+=std::abs(double(l[i])-double(r[i]));
    check(difference>0.01,"stereo channels have distinct delay structure");
    const double longEnergy=energy(l,rate/2,rate*2);

    effect.reset();impulse(shortTail,unused);state.decaySeconds=.1f;
    effect.process(shortTail.data(),unused.data(),frames,rate,state);
    check(longEnergy > energy(shortTail,rate/2,rate*2)*100,"decay parameter changes measured late tail");

    effect.reset();impulse(l,r);state.decaySeconds=2;state.damping=0;
    effect.process(l.data(),r.data(),frames,rate,state);
    const double brightEnergy=energy(l,rate/5,rate);
    effect.reset();impulse(shortTail,unused);state.damping=1;
    effect.process(shortTail.data(),unused.data(),frames,rate,state);
    check(brightEnergy > energy(shortTail,rate/5,rate),"damping changes the measured tail");

    effect.reset();std::fill(l.begin(),l.end(),0);std::fill(r.begin(),r.end(),0);
    effect.process(l.data(),r.data(),frames,rate,state);
    check(energy(l,0,l.size())==0 && energy(r,0,r.size())==0,"reset discards prior tail without stale buffer data");

    effect.reset();impulse(l,r);state.decaySeconds=2;state.dryWet=1;
    effect.process(l.data(),r.data(),rate/2,rate,state);
    std::fill(l.begin(),l.end(),0);std::fill(r.begin(),r.end(),0);
    effect.process(l.data(),r.data(),rate/2,96000,state);
    check(energy(l,0,rate/2)==0 && energy(r,0,rate/2)==0,"sample-rate change resets old-rate history");

    for (const double sampleRate : {8000.0,384000.0}) {
        effect.reset();impulse(l,r);effect.process(l.data(),r.data(),frames,sampleRate,state);
        check(finite(l)&&finite(r)&&energy(l,1,std::size_t(sampleRate*.1))>1e-7,"rate boundary produces finite delayed output");
    }
    effect.reset();std::fill(l.begin(),l.end(),.25f);l[3]=std::numeric_limits<float>::quiet_NaN();
    l[4]=std::numeric_limits<float>::infinity();l[5]=std::numeric_limits<float>::max();
    effect.process(l.data(),l.data(),frames,rate,state);
    check(finite(l) && l[3]==0 && l[4]==0,"nonfinite input cannot poison state; aliased stereo safely becomes mono");
    effect.reset();std::fill(l.begin(),l.end(),.1f);state.dryWet=0;
    effect.process(l.data(),nullptr,128,rate,state);state.dryWet=1;std::fill(l.begin(),l.end(),.1f);
    observe=true;effect.process(l.data(),nullptr,512,rate,state);observe=false;
    check(allocations==0,"audio processing has no heap allocation");
    check(l[0]>.09f&&l[0]<.1f && l[300]==0,"wet changes ramp over five milliseconds");
    if(failures)return 1;std::cout << "Native reverb DSP passed\n";return 0;
}
