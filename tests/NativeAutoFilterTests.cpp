#include "core/NativeAutoFilter.h"
#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstdlib>
#include <iostream>
#include <limits>
#include <new>
#include <numbers>
#include <vector>

namespace {std::atomic<bool> watching{false};std::atomic<unsigned> allocations{0};}
void* operator new(std::size_t n){if(watching.load())++allocations;if(auto* p=std::malloc(n?n:1))return p;throw std::bad_alloc();}
void* operator new[](std::size_t n){return ::operator new(n);}
void operator delete(void* p) noexcept {std::free(p);}
void operator delete[](void* p) noexcept {std::free(p);}
void operator delete(void* p,std::size_t) noexcept {std::free(p);}
void operator delete[](void* p,std::size_t) noexcept {std::free(p);}

using namespace emusician::autofilter;
namespace {
int failures=0;
void check(bool ok,const char* name){if(!ok){std::cerr<<"FAIL: "<<name<<'\n';++failures;}}
double rms(const std::vector<float>& data,std::size_t begin,std::size_t end){
    double sum=0;for(auto i=begin;i<end;++i)sum+=double(data[i])*data[i];return std::sqrt(sum/double(end-begin));
}
std::vector<float> sine(double hz,double rate,int n){std::vector<float> out(n);for(int i=0;i<n;++i)out[i]=float(std::sin(2*std::numbers::pi*hz*i/rate));return out;}
}
int main(){
    constexpr double rate=48000;constexpr int n=48000;
    Settings s;Filter low,high;auto bass=sine(200,rate,n),treble=sine(8000,rate,n);
    low.process(bass.data(),nullptr,n,rate,s);high.process(treble.data(),nullptr,n,rate,s);
    check(rms(bass,n/2,n)>.68 && rms(treble,n/2,n)<.03,"low-pass preserves bass and rejects treble");
    s.mode=Mode::highPass;low.reset();high.reset();bass=sine(200,rate,n);treble=sine(8000,rate,n);
    low.process(bass.data(),nullptr,n,rate,s);high.process(treble.data(),nullptr,n,rate,s);
    check(rms(bass,n/2,n)<.04 && rms(treble,n/2,n)>.68,"high-pass rejects bass and preserves treble");

    s=Settings{};s.lfoEnabled=true;s.lfoHz=2;s.lfoDepth=1;
    auto lfo=sine(1000,rate,n),fixed=lfo;Filter moving,stationary;
    moving.process(lfo.data(),nullptr,n,rate,s);s.lfoEnabled=false;stationary.process(fixed.data(),nullptr,n,rate,s);
    double difference=0;for(int i=n/2;i<n;++i)difference+=std::abs(lfo[i]-fixed[i]);
    check(difference/n>.05,"LFO audibly alters the real filtered output");

    s=Settings{};s.dryWet=0;auto dry=sine(8000,rate,n);auto copy=dry;Filter transparent;
    watching=true;transparent.process(dry.data(),nullptr,n,rate,s);watching=false;
    check(allocations==0 && dry==copy,"dry output is transparent and audio callback does not allocate");
    s.dryWet=1;transparent.process(dry.data(),nullptr,n,rate,s);
    check(std::isfinite(dry.back()),"dry/wet transition remains finite");
    auto changedRate=sine(1000,96000,n);transparent.process(changedRate.data(),nullptr,n,96000,s);
    check(std::all_of(changedRate.begin(),changedRate.end(),[](float x){return std::isfinite(x);}),"sample rate change remains stable");
    auto invalid=s;invalid.resonanceQ=std::numeric_limits<float>::quiet_NaN();check(!valid(invalid),"NaN resonance rejected");
    invalid=s;invalid.frequencyHz=20001;check(!valid(invalid),"cutoff outside range rejected");
    invalid=s;invalid.lfoDepth=1.01f;check(!valid(invalid),"LFO depth outside range rejected");
    invalid=s;invalid.mode=static_cast<Mode>(123);check(!valid(invalid),"unsupported mode rejected");
    if(failures)return 1;std::cout<<"Native Auto Filter DSP passed\n";return 0;
}
