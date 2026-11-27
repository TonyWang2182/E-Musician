#include "core/NativeEffects.h"
#include <array>
#include <chrono>
#include <cmath>
#include <iostream>
#include <numbers>
using namespace emusician::effects;
int main(){
    constexpr int size=256, blocks=20000, rate=48000;
    std::array<float,size> source{},left{},right{};
    EqSettings eq;for(auto& b:eq.bands)b.gainDb=3;
    CompressorSettings settings;Equalizer filter;Compressor compressor;
    for(int i=0;i<size;++i)source[i]=float(.2*std::sin(2*std::numbers::pi*440*i/rate));
    const auto start=std::chrono::steady_clock::now();
    for(int i=0;i<blocks;++i){left=source;right=source;filter.process(left.data(),right.data(),size,rate,eq);compressor.process(left.data(),right.data(),size,rate,settings);}
    const double seconds=std::chrono::duration<double>(std::chrono::steady_clock::now()-start).count();
    std::cout<<"mode=offline_rate_48000_block_256_8eq_plus_compressor blocks="<<blocks<<" audio_seconds="<<double(size*blocks)/rate<<" elapsed_seconds="<<seconds<<" realtime_multiple="<<double(size*blocks)/rate/seconds<<" checksum="<<left[0]<<'\n';
}
