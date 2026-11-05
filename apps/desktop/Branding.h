#pragma once
#include "UiDesign.h"
#include "BrandAssets.h"

namespace emusician::brand {
// Decode once on the UI thread. The original user-approved raster is unchanged.
inline const juce::Image& logo() {
    static const auto image = juce::ImageFileFormat::loadFrom(emusician_brand::yiyueshilogo_png,
                                                            emusician_brand::yiyueshilogo_pngSize);
    return image;
}
inline void draw(juce::Graphics& g, juce::Rectangle<float> bounds, float opacity = 1.0f) {
    g.setOpacity(opacity);
    g.drawImage(logo(), bounds, juce::RectanglePlacement::centred);
    g.setOpacity(1.0f);
}
class Startup final : public juce::Component, private juce::Timer {
public:
    explicit Startup(juce::String appVersion = {}) : version(std::move(appVersion)) { setInterceptsMouseClicks(true, true); setWantsKeyboardFocus(true); }
    void start() { elapsed = 0; setAlpha(1); setVisible(true); toFront(false); if(isShowing())grabKeyboardFocus(); startTimerHz(30); }
    void paint(juce::Graphics& g) override {
        g.fillAll(design::paper);
        auto centre = getLocalBounds().toFloat().getCentre();
        const auto opacity = juce::jlimit(0.0f, 1.0f, float(elapsed + 1) / 7.0f);
        draw(g, {centre.x - 72, centre.y - 126, 144, 144}, opacity);
        g.setColour(design::ink.withAlpha(opacity)); g.setFont(design::labelFont(25, true));
        g.drawText(juce::String::fromUTF8("易乐师"), int(centre.x - 150), int(centre.y + 34), 300, 36, juce::Justification::centred);
        g.setColour(design::secondary.withAlpha(opacity)); g.setFont(design::labelFont(14));
        g.drawText("E-musician  " + version, int(centre.x - 150), int(centre.y + 78), 300, 24, juce::Justification::centred);
    }
    void mouseDown(const juce::MouseEvent&) override { finish(); }
    bool keyPressed(const juce::KeyPress&) override { finish(); return true; }
private:
    void finish() { stopTimer(); setAlpha(1); setVisible(false); }
    void timerCallback() override {
        if (++elapsed >= 27) { finish(); return; }
        if (elapsed > 15) setAlpha(float(27 - elapsed) / 12.0f);
        repaint();
    }
    int elapsed = 0;
    juce::String version;
};
}
