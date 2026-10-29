#pragma once
#include "Time.hpp"
#include <charconv>
#include <iomanip>
#include <optional>
#include <sstream>
#include <string>
#include <string_view>

namespace emusician::time {
// Display beats use the meter denominator; engine/MIDI beats remain quarters.
// 960 display ticks per denominator beat; one-based bars and beats.
inline std::string musicalPosition(double seconds, double bpm, int numerator, int denominator)
{
    if(numerator<1||denominator<1)return {};
    const auto units=secondsToBeats(seconds,bpm)*double(denominator)/4.0*960.0;
    if(!std::isfinite(units)||units<0||units>=0x1p62)return {};
    const auto ticks=static_cast<std::int64_t>(std::llround(units));
    std::ostringstream result;
    result << ticks/(960*numerator)+1 << ':' << (ticks/960)%numerator+1 << ':'
           << std::setw(3) << std::setfill('0') << ticks%960;
    return result.str();
}
inline std::optional<double> parseMusicalPosition(std::string_view text,double bpm,int numerator,int denominator)
{
    if(numerator<1||denominator<1||!std::isfinite(bpm)||bpm<=0)return {};
    std::int64_t values[3]{};
    for(int i=0;i<3;++i){
        const auto colon=text.find(':');
        if((i<2&&colon==std::string_view::npos)||(i==2&&colon!=std::string_view::npos))return {};
        const auto part=text.substr(0,colon);if(part.empty())return {};
        const auto parsed=std::from_chars(part.data(),part.data()+part.size(),values[i]);
        if(parsed.ec!=std::errc()||parsed.ptr!=part.data()+part.size())return {};
        if(i<2)text.remove_prefix(colon+1);
    }
    if(values[0]<1||values[0]>10000000||values[1]<1||values[1]>numerator||values[2]<0||values[2]>=960)return {};
    const double beats=((double(values[0])-1)*numerator+double(values[1])-1+double(values[2])/960.0)*4.0/denominator;
    return beatsToSeconds(beats,bpm);
}
}
