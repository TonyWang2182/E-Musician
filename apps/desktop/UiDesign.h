#pragma once
#include <juce_gui_basics/juce_gui_basics.h>

namespace emusician::design {
inline const juce::Colour paper {0xfffefefd}, panel {0xfff1f2ee}, ink {0xff171817},
    secondary {0xff626560}, rule {0xffc6c9c3}, accent {0xffbfd2cf}, focus {0xff527d7a};
inline juce::Font labelFont(float size, bool bold = false) {
    return juce::Font(juce::FontOptions(juce::Font::getDefaultSansSerifFontName(), size,
                                      bold ? juce::Font::bold : juce::Font::plain));
}
inline juce::Font numberFont(float size, bool bold = false) {
    return juce::Font(juce::FontOptions(juce::Font::getDefaultMonospacedFontName(), size,
                                      bold ? juce::Font::bold : juce::Font::plain));
}
inline juce::Colour trackColour(const juce::String& value) {
    return value.length() == 7 && value.startsWithChar('#')
        ? juce::Colour(0xff000000u | static_cast<juce::uint32>(value.substring(1).getHexValue32()))
        : juce::Colour(0xffa4aaa4);
}
inline juce::Colour trackFill(const juce::String& value) {
    return paper.interpolatedWith(trackColour(value), .24f);
}
inline const char* trackPalette[] {"#7EA49D", "#91A7C3", "#AC9AC1", "#CA9C9A", "#C8B383", "#A4B78D", "#87B4BC", "#B69E8B", "#9EA5AA", "#C3A3B3"};
}
