#pragma once
#include <juce_gui_basics/juce_gui_basics.h>

namespace emusician::focus {
inline const juce::Colour base { 0xff17191d }, canvas { 0xff1c1f23 }, panel { 0xff25292e }, raised { 0xff2d3238 };
inline const juce::Colour line { 0xff3b4046 }, strong { 0xff606872 }, text { 0xffeceeea }, muted { 0xffabb2bb }, dim { 0xff8e98a3 };
inline const juce::Colour accent { 0xffd8b879 }, danger { 0xffe28780 }, green { 0xff86b6a1 };
inline juce::Font font(float height, int style = juce::Font::plain)
{
    // JUCE's height includes line metrics; compensate for Segoe UI's small cap height.
    return juce::Font(juce::FontOptions("Segoe UI", height * 1.15f, style));
}
inline juce::Colour trackColour(const juce::String& kind, int index)
{
    if (kind == "bus" || kind == "master") return juce::Colour(0xffa6acb5);
    if (kind == "instrument" || kind == "midi") return juce::Colour(0xffb7a6ce);
    const juce::Colour colours[] { juce::Colour(0xff89b5c3), juce::Colour(0xffc9a68c), juce::Colour(0xffa4ba94), juce::Colour(0xff88aaa5) };
    return colours[juce::jmax(0, index) % 4];
}
}
