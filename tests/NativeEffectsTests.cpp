#include "core/NativeEffects.h"
#include <algorithm>
#include <array>
#include <atomic>
#include <cmath>
#include <cstdlib>
#include <iostream>
#include <limits>
#include <new>

namespace { std::atomic<bool> observe{false}; std::atomic<unsigned> allocations{0}; }
void* operator new(std::size_t n) { if(observe.load())++allocations; if(auto* p=std::malloc(n?n:1))return p;throw std::bad_alloc(); }
void* operator new[](std::size_t n) { return ::operator new(n); }
void operator delete(void* p) noexcept { std::free(p); }
void operator delete[](void* p) noexcept { std::free(p); }
void operator delete(void* p,std::size_t) noexcept { std::free(p); }
void operator delete[](void* p,std::size_t) noexcept { std::free(p); }
using namespace emusician::effects;
namespace {
int failures=0;
void check(bool ok,const char* s){ if(!ok){std::cerr<<"FAIL: "<<s<<'\n';++failures;} }
bool near(double a,double b,double tolerance=1e-4){return std::abs(a-b)<tolerance;}
}
int main(){
    std::array<float,4096> l{},r{};
    EqSettings eq; Equalizer filter;
    l[0]=1;r[0]=-.5f;filter.process(l.data(),r.data(),int(l.size()),48000,eq);
    check(l[0]==1 && r[0]==-.5f && l[1]==0,"flat EQ is transparent for stereo impulse");
    eq.bands[4].frequency=1000;eq.bands[4].gainDb=12;eq.bands[4].q=1;
    for(std::size_t i=0;i<l.size();++i){l[i]=std::sin(2*3.141592653589793*1000*i/48000);r[i]=l[i];}
    filter.reset();filter.process(l.data(),r.data(),int(l.size()),48000,eq);
    double peak=0;for(std::size_t i=2000;i<l.size();++i)peak=std::max(peak,double(std::abs(l[i])));
    check(peak>3.8&&peak<4.2,"peak band boosts target frequency by 12 dB");
    check(near(responseDb(1000,48000,eq),12,.01),"curve equals filter response at peak");
    eq.bands[4].enabled=false;l.fill(0);l[0]=1;filter.reset();filter.process(l.data(),nullptr,int(l.size()),48000,eq);
    check(l[0]==1&&l[1]==0,"disabled band bypasses in mono");
    eq.bands[0].gainDb=12;eq.bands[7].gainDb=-12;filter.reset();
    l.fill(0);l[0]=1;filter.process(l.data(),nullptr,int(l.size()),48000,eq);
    bool finite=true;for(float v:l)finite=finite&&std::isfinite(v);check(finite,"shelving response is finite");
    eq.bands[3].q=std::numeric_limits<float>::quiet_NaN();check(!valid(eq),"invalid EQ rejected");
    {
        EqSettings shaped;
        auto& band = shaped.bands[3]; band.frequency=1000;band.q=.7071068f;band.gainDb=0;
        band.shape=FilterShape::highPass;
        check(responseDb(100,48000,shaped)<-39 && std::abs(responseDb(10000,48000,shaped))<.1,"high pass cuts bass at zero gain");
        check(near(responseDb(1000,48000,shaped),-3.0103,.01),"12dB high pass has expected cutoff");
        l.fill(0);l[0]=1;filter.reset();observe=true;filter.process(l.data(),nullptr,int(l.size()),48000,shaped);observe=false;
        double dc=0;for(float v:l)dc+=v;check(std::abs(dc)<.0001 && l[0]>.5,"rendered high pass removes DC (not a flat gain-only bypass)");
        band.shape=FilterShape::lowPass;
        check(responseDb(10000,48000,shaped)<-39 && std::abs(responseDb(100,48000,shaped))<.1,"low pass cuts highs and keeps bass");
        band.shape=FilterShape::notch;band.q=2;
        check(responseDb(1000,48000,shaped)<-100 && responseDb(100,48000,shaped)>-.1,"notch rejects its center only");
        band.shape=FilterShape::lowShelf;band.gainDb=12;
        check(responseDb(20,48000,shaped)>11.9 && std::abs(responseDb(20000,48000,shaped))<.1,"shelf can be placed on a middle band");
        for(auto shape:{FilterShape::bell,FilterShape::lowShelf,FilterShape::highShelf,FilterShape::highPass,FilterShape::lowPass,FilterShape::notch}) {
            FilterShape parsed=FilterShape::legacy;check(parseShape(shapeName(shape),parsed)&&parsed==shape,"shape names round trip");
            for(double rate:{8000.0,44100.0,48000.0,192000.0}) {
                band.shape=shape;band.frequency=20000;band.q=10;band.gainDb=24;l.fill(0);l[0]=1;filter.reset();
                observe=true;filter.process(l.data(),nullptr,int(l.size()),rate,shaped);observe=false;
                check(std::all_of(l.begin(),l.end(),[](float v){return std::isfinite(v);}),"shapes finite at maximum Q/gain and Nyquist clamp");
            }
        }
        FilterShape parsed;check(!parseShape("unsupported",parsed),"unknown shape rejected");
        band.shape=static_cast<FilterShape>(999);check(!valid(shaped),"invalid enum rejected");
        EqSettings old,explicitShape;for(std::size_t i=0;i<8;++i){old.bands[i].gainDb=3;explicitShape.bands[i]=old.bands[i];explicitShape.bands[i].shape=effectiveShape(FilterShape::legacy,i);}
        for(double f:{40.0,1000.0,16000.0})check(near(responseDb(f,48000,old),responseDb(f,48000,explicitShape),1e-9),"legacy fixed shelves keep exact response");
    }
    CompressorSettings s;Compressor comp;l.fill(.5f);r.fill(-.5f);
    comp.process(l.data(),r.data(),int(l.size()),48000,s);
    check(std::abs(l.back())<.3f && near(l.back(),-r.back()),"stereo linked detector handles antiphase");
    s.ratio=1;comp.reset();l.fill(.5f);comp.process(l.data(),nullptr,int(l.size()),48000,s);
    check(near(l.back(),.5),"ratio 1 is transparent");
    l.fill(.5f);l[10]=std::numeric_limits<float>::quiet_NaN();l[20]=std::numeric_limits<float>::infinity();
    comp.reset();comp.process(l.data(),l.data(),int(l.size()),48000,s);
    check(l[10]==0&&l[20]==0&&std::isfinite(l.back()),"nonfinite input cannot poison compressor and aliased mono is safe");
    eq=EqSettings{};eq.bands[1].gainDb=6;l.fill(.1f);l[1]=std::numeric_limits<float>::infinity();
    filter.reset();filter.process(l.data(),l.data(),int(l.size()),48000,eq);
    check(std::isfinite(l[1])&&std::isfinite(l.back()),"nonfinite input cannot poison EQ and aliased mono is safe");
    s.ratio=0;check(!valid(s),"invalid ratio rejected");
    s=CompressorSettings{};s.attackMs=.1f;s.thresholdDb=-30;s.ratio=10;s.makeupDb=6;
    std::array<float,4096> dry{},wet{},mixed{};dry.fill(.5f);wet=dry;mixed=dry;
    Compressor d,w,m;s.dryWet=0;d.process(dry.data(),nullptr,int(dry.size()),48000,s);
    s.dryWet=1;w.process(wet.data(),nullptr,int(wet.size()),48000,s);
    s.dryWet=.5f;m.process(mixed.data(),nullptr,int(mixed.size()),48000,s);
    check(near(dry.back(),.5)&&wet.back()<dry.back(),"dry/wet endpoints preserve dry and compress wet");
    check(near(mixed.back(),(dry.back()+wet.back())*.5),"50 percent mix is linear dry and wet sum");
    check(d.lastReductionDb()>10&&near(d.lastReductionDb(),w.lastReductionDb(),.001),"meter measures wet-path reduction even for dry output");
    s.ratio=1;w.reset();wet.fill(.5f);w.process(wet.data(),nullptr,int(wet.size()),48000,s);
    check(near(w.lastReductionDb(),0),"ratio one has zero gain reduction");
    Compressor transition;CompressorSettings fade;fade.ratio=1;fade.makeupDb=6;fade.dryWet=0;
    std::array<float,512> ramp{};ramp.fill(.2f);transition.process(ramp.data(),nullptr,128,48000,fade);
    fade.dryWet=1;ramp.fill(.2f);transition.process(ramp.data(),nullptr,int(ramp.size()),48000,fade);
    check(ramp[0]>.2&&ramp[0]<.21&&ramp[100]>ramp[0]&&ramp.back()>.39,"dry/wet changes use a short, click-reducing ramp");
    StereoDelay delay;DelaySettings ds;ds.delayMs=10;ds.feedback=.5f;ds.dryWet=1;
    l.fill(0);r.fill(0);l[0]=1;r[0]=.5f;observe=true;delay.process(l.data(),r.data(),int(l.size()),48000,ds);observe=false;
    check(near(l[0],0)&&near(l[480],1)&&near(l[960],.5)&&near(r[480],.5),"stereo delay echoes at delay time with feedback");
    check(allocations==0,"delay audio processing does not allocate");
    delay.reset();l.fill(0);r.fill(0);delay.process(l.data(),r.data(),int(l.size()),48000,ds);
    check(near(l[480],0),"delay reset discards the old tail without clearing the ring");
    ds.feedback=.96f;check(!valid(ds),"unstable delay feedback rejected");
    s.dryWet=1.01f;check(!valid(s),"out-of-range mix rejected");
    s.ratio=4;s.dryWet=1;eq=EqSettings{};l.fill(.1f);r.fill(.1f);observe=true;
    filter.process(l.data(),r.data(),int(l.size()),48000,eq);comp.process(l.data(),r.data(),int(l.size()),48000,s);
    observe=false;check(allocations==0,"rendering does not allocate");
    if(failures)return 1;std::cout<<"Native effects DSP passed\n";return 0;
}
