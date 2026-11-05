// Included inside NativeEffectsPanel::Impl. A bounded, message-thread preview
// of parameters and a bounded output FFT snapshot; never owns live audio DSP.
struct Graph final : juce::Component {
    explicit Graph(Impl& parent) : p(parent) { setWantsKeyboardFocus(true); }
    void invalidate() { dirty = true; repaint(); }
    void resized() override { dirty = true; }
    void focusLost(FocusChangeType) override {if(moving){moving=false;p.cancelGesture();}}
    juce::Rectangle<float> plot() const { return getLocalBounds().toFloat().reduced(35, 26); }
    double rate() const { return p.sampleRate > 0 ? p.sampleRate : 48000.0; }
    double upper() const { return std::min(20000.0, rate() * .49); }
    float frequencyX(double hz, juce::Rectangle<float> a) const {
        return a.getX() + float(std::log(juce::jlimit(20.0, upper(), hz) / 20.0) / std::log(upper() / 20.0)) * a.getWidth();
    }
    static double compressorOutputDb(double input, double threshold, double ratio, double makeup, double mix = 1.0) {
        const double wetDb = input <= threshold ? input + makeup : threshold + (input - threshold) / ratio + makeup;
        return 20.0 * std::log10((1.0 - mix) * std::pow(10.0, input / 20.0) + mix * std::pow(10.0, wetDb / 20.0));
    }
    static bool gainShape(const juce::var& band) {
        const auto shape = band["shape"].toString();
        return shape != "high_pass" && shape != "low_pass" && shape != "notch";
    }
    juce::Point<float> bandPoint(const juce::var& band, juce::Rectangle<float> a) const {
        const double gain = gainShape(band) ? juce::jlimit(-24.0, 24.0, double(band["gain_db"])) : 0.0;
        // Numeric controls retain the requested cutoff; at low device rates
        // the graph node follows the actual DSP cutoff, just like the curve.
        return {frequencyX(std::min(double(band["frequency"]), rate() * .475), a), a.getCentreY() - float(gain / 48.0) * a.getHeight()};
    }
    void handle(juce::Graphics& g, juce::Point<float> point, const juce::String& label, bool active = true) {
        g.setColour(active ? ink : quiet); g.fillEllipse(point.x - 8, point.y - 8, 16, 16);
        g.setColour(paper); g.setFont(mono(10));
        g.drawText(label, int(point.x) - 8, int(point.y) - 8, 16, 16, juce::Justification::centred);
    }
    void text(juce::Graphics& g, const juce::String& value, int x, int y, int w,
              juce::Justification alignment = juce::Justification::left) {
        g.setColour(quiet); g.setFont(mono(10)); g.drawText(value, x, y, w, 16, alignment);
    }
    void frequencyGrid(juce::Graphics& g, juce::Rectangle<float> a, bool eq) {
        g.setColour(rule); g.drawRect(a);
        for (const auto f : {100.0, 1000.0, 10000.0}) {
            const auto x = frequencyX(f, a); g.setColour(rule); g.drawVerticalLine(int(x), a.getY(), a.getBottom());
            text(g, f < 1000 ? "100" : f < 10000 ? "1k" : "10k", int(x) - 16, int(a.getBottom()) + 2, 32, juce::Justification::centred);
        }
        const auto zero = eq ? a.getCentreY() : a.getY() + a.getHeight() * 24.0f / 84.0f;
        g.setColour(rule); g.drawHorizontalLine(int(zero), a.getX(), a.getRight());
        text(g, "+24", 0, int(a.getY()) - 7, 30, juce::Justification::centredRight);
        text(g, "0", 0, int(zero) - 7, 30, juce::Justification::centredRight);
        text(g, eq ? "-24" : "-60", 0, int(a.getBottom()) - 7, 30, juce::Justification::centredRight);
        text(g, "Hz", int(a.getX()), int(a.getBottom()) + 2, 20);
    }
    void paint(juce::Graphics& g) override {
        g.fillAll(paper); const auto a = plot(); if (a.getWidth() < 12 || a.getHeight() < 12) return;
        const auto type = p.state["type"].toString();
        if (type == "eq8") paintEq(g, a);
        else if (type == "compressor") paintCompressor(g, a);
        else if (type == "delay") paintDelay(g, a);
        else if (type == "reverb") paintReverb(g, a);
        else if (type == "auto_filter") paintFilter(g, a);
        if (hasKeyboardFocus(true)) { g.setColour(ink); g.drawRect(getLocalBounds().reduced(1)); }
    }
    void paintEq(juce::Graphics& g, juce::Rectangle<float> a) {
        frequencyGrid(g,a,true);
        if(a.getWidth()>400)text(g,uiText("EQ response", "均衡曲线"),int(a.getX()),2,int(a.getWidth()*.4f));
        text(g,p.spectrumAvailable?uiText("Mono output / 0 to -90 dBFS", "单声道输出 / 0至-90 dBFS"):uiText("Spectrum inactive", "频谱未活动"),int(a.getX()),2,int(a.getWidth()),juce::Justification::right);
        if(p.spectrumAvailable){juce::Path spectrum;spectrum.startNewSubPath(a.getBottomLeft());
            for(std::size_t i=0;i<p.spectrumDb.size();++i)spectrum.lineTo(a.getX()+float(i)*a.getWidth()/float(p.spectrumDb.size()-1),a.getBottom()-((p.spectrumDb[i]+90)/90)*a.getHeight());
            spectrum.lineTo(a.getBottomRight());spectrum.closeSubPath();g.setColour(deviceui::accent.withAlpha(.55f));g.fillPath(spectrum);
        }
        if (dirty) {
            effects::EqSettings settings;
            if (auto* bands = p.state["bands"].getArray()) for (int i = 0; i < 8 && i < bands->size(); ++i) {
                const auto b = bands->getReference(i); auto& target = settings.bands[std::size_t(i)];
                target.enabled = bool(b["enabled"]); target.frequency = float(double(b["frequency"]));
                target.gainDb = float(double(b["gain_db"])); target.q = float(double(b["q"]));
                if (b.hasProperty("shape")) effects::parseShape(b["shape"].toString().toStdString(), target.shape);
            }
            curve.clear();
            for (int x = 0; x < 180; ++x) {
                const auto hz = 20.0 * std::pow(upper() / 20.0, double(x) / 179.0);
                const auto db = juce::jlimit(-24.0, 24.0, effects::responseDb(hz, rate(), settings));
                const auto px = a.getX() + a.getWidth() * float(x) / 179.0f;
                const auto py = a.getCentreY() - float(db / 48.0) * a.getHeight();
                if (x == 0) curve.startNewSubPath(px, py); else curve.lineTo(px, py);
            }
            dirty = false;
        }
        g.setColour(ink); g.strokePath(curve, juce::PathStrokeType(1.6f));
        if (auto* bands = p.state["bands"].getArray()) for (int i = 0; i < bands->size() && i < 8; ++i) {
            const auto b = bands->getReference(i); const auto pt = bandPoint(b, a);
            if (i == p.selectedBand) { g.setColour(quiet); g.drawEllipse(pt.x - 11, pt.y - 11, 22, 22, 1); }
            handle(g, pt, juce::String(i + 1), bool(b["enabled"]));
        }
    }
    juce::Point<float> compressorPoint(double input, double output, juce::Rectangle<float> a) const {
        return {a.getX() + float((input + 60.0) / 60.0) * a.getWidth(),
                a.getBottom() - float((juce::jlimit(-60.0, 24.0, output) + 60.0) / 84.0) * a.getHeight()};
    }
    juce::Point<float> thresholdPoint(juce::Rectangle<float> a) const {
        const double t = double(p.state["threshold_db"]); return compressorPoint(t, t + double(p.state["makeup_db"]), a);
    }
    juce::Point<float> ratioPoint(juce::Rectangle<float> a) const {
        return compressorPoint(0, compressorOutputDb(0, double(p.state["threshold_db"]), double(p.state["ratio"]), double(p.state["makeup_db"])), a);
    }
    void paintCompressor(juce::Graphics& g, juce::Rectangle<float> a) {
        g.setColour(rule); g.drawRect(a);
        text(g, "Wet / T: threshold  R: ratio", int(a.getX()), 2, int(a.getWidth()));
        for (int db : {-48, -36, -24, -12, 0}) {
            const auto pt = compressorPoint(db, db, a); g.setColour(rule);
            g.drawVerticalLine(int(pt.x), a.getY(), a.getBottom()); g.drawHorizontalLine(int(pt.y), a.getX(), a.getRight());
        }
        text(g, "+24", 0, int(a.getY()) - 7, 30, juce::Justification::centredRight);
        text(g, "-60", 0, int(a.getBottom()) - 7, 30, juce::Justification::centredRight);
        text(g, "-60 dB input", int(a.getX()), int(a.getBottom()) + 2, 100);
        text(g, "0 dB", int(a.getRight()) - 40, int(a.getBottom()) + 2, 40, juce::Justification::right);
        const float dashes[] {3, 3}; g.setColour(rule);
        g.drawDashedLine(juce::Line<float>(compressorPoint(-60, -60, a), compressorPoint(0, 0, a)), dashes, 2);
        const double threshold = double(p.state["threshold_db"]), ratio = double(p.state["ratio"]), makeup = double(p.state["makeup_db"]);
        juce::Path response;
        for (int i = 0; i <= 120; ++i) {
            const auto input = -60.0 + i * .5;
            const auto pt = compressorPoint(input, compressorOutputDb(input, threshold, ratio, makeup), a);
            if (i == 0) response.startNewSubPath(pt); else response.lineTo(pt);
        }
        g.setColour(ink); g.strokePath(response, juce::PathStrokeType(1.6f));
        handle(g, thresholdPoint(a), "T"); if (threshold < 0) handle(g, ratioPoint(a), "R");
        const auto meterArea = juce::Rectangle<float>(a.getX(), a.getY() + 3, juce::jmin(120.0f, a.getWidth() * .3f), 4);
        g.setColour(rule); g.fillRect(meterArea);
        if (p.meterAvailable) { g.setColour(ink); g.fillRect(meterArea.withWidth(meterArea.getWidth() * juce::jlimit(0.0f, 1.0f, p.reductionDb / 36.0f))); }
    }
    double delayHorizon() const { return moving ? frozenHorizon : std::max(1000.0, double(p.state["delay_ms"]) * 6.0); }
    juce::Point<float> delayPoint(juce::Rectangle<float> a, bool feedback) const {
        return {a.getX() + float(double(p.state["delay_ms"]) * (feedback ? 2.0 : 1.0) / delayHorizon()) * a.getWidth(),
                a.getBottom() - float(double(p.state["dry_wet"]) * (feedback ? double(p.state["feedback"]) : 1.0)) * a.getHeight()};
    }
    void paintDelay(juce::Graphics& g, juce::Rectangle<float> a) {
        g.setColour(rule); g.drawRect(a);
        text(g, "Echo guide / T: time  F: feedback", int(a.getX()), 2, int(a.getWidth()));
        const auto time = double(p.state["delay_ms"]), feedback = double(p.state["feedback"]), mix = double(p.state["dry_wet"]);
        for (int tap = 0; tap <= 8; ++tap) {
            const auto x = a.getX() + float(tap * time / delayHorizon()) * a.getWidth(); if (x > a.getRight()) break;
            const auto level = tap == 0 ? 1.0 - mix : mix * std::pow(feedback, tap - 1);
            g.setColour(tap == 0 ? quiet : ink); g.drawLine(x, a.getBottom(), x, a.getBottom() - float(level) * a.getHeight(), tap == 0 ? 2 : 3);
        }
        text(g, "100%", 0, int(a.getY()) - 7, 31, juce::Justification::centredRight);
        text(g, "0", 0, int(a.getBottom()) - 7, 31, juce::Justification::centredRight);
        text(g, "0 ms", int(a.getX()), int(a.getBottom()) + 2, 44);
        text(g, juce::String(delayHorizon(), 0) + " ms", int(a.getRight()) - 90, int(a.getBottom()) + 2, 90, juce::Justification::right);
        handle(g, delayPoint(a, false), "T"); handle(g, delayPoint(a, true), "F");
    }
    double reverbHorizon() const { return moving ? frozenHorizon : std::max(2.0, double(p.state["decay_seconds"]) * 1.2); }
    juce::Point<float> decayPoint(juce::Rectangle<float> a) const {
        return {a.getX() + float(double(p.state["decay_seconds"]) / reverbHorizon()) * a.getWidth(), a.getBottom()};
    }
    void paintReverb(juce::Graphics& g, juce::Rectangle<float> a) {
        g.setColour(rule); g.drawRect(a);
        text(g, "RT60 guide / D: decay", int(a.getX()), 2, int(a.getWidth()));
        const double decay = double(p.state["decay_seconds"]);
        for (int db : {-20, -40}) { g.setColour(rule); const auto y = a.getY() + a.getHeight() * float(-db) / 60; g.drawHorizontalLine(int(y), a.getX(), a.getRight()); }
        const auto point = decayPoint(a);
        juce::Path area; area.startNewSubPath(a.getX(), a.getY()); area.lineTo(point); area.lineTo(a.getX(), a.getBottom()); area.closeSubPath();
        g.setColour(juce::Colour(0xffeceee8)); g.fillPath(area);
        g.setColour(ink); g.drawLine(juce::Line<float>(a.getTopLeft(), point), 1.6f); handle(g, point, "D");
        text(g, "0 dB", 0, int(a.getY()) - 7, 31, juce::Justification::centredRight);
        text(g, "-60", 0, int(a.getBottom()) - 7, 31, juce::Justification::centredRight);
        text(g, "0 s", int(a.getX()), int(a.getBottom()) + 2, 35);
        text(g, juce::String(decay, 2) + " s RT60", int(a.getRight()) - 100, int(a.getBottom()) + 2, 100, juce::Justification::right);
        const auto bar = juce::Rectangle<float>(a.getRight() - 110, a.getY() + 26, 100, 5);
        text(g, "HF damping", int(bar.getX()), int(bar.getY()) - 18, 105);
        g.setColour(rule); g.fillRect(bar); g.setColour(ink); g.fillRect(bar.withWidth(bar.getWidth() * float(double(p.state["damping"]))));
    }
    double filterDb(double hz) const {
        // Same RBJ low/high pass coefficients as NativeAutoFilter::Filter,
        // evaluated at the unmodulated centre cutoff. No audio is sampled.
        const auto w = 2 * juce::MathConstants<double>::pi * juce::jlimit(20.0, rate() * .45, double(p.state["frequency_hz"])) / rate();
        const auto cs = std::cos(w), alpha = std::sin(w) / (2 * double(p.state["resonance_q"])), a0 = 1 + alpha;
        const bool high = p.state["mode"].toString() == "high_pass";
        const double b0 = (high ? 1 + cs : 1 - cs) * .5 / a0, b1 = (high ? -(1 + cs) : 1 - cs) / a0;
        const double a1 = -2 * cs / a0, a2 = (1 - alpha) / a0;
        const auto z = std::polar(1.0, -2 * juce::MathConstants<double>::pi * hz / rate());
        const auto response = (b0 + b1 * z + b0 * z * z) / (1.0 + a1 * z + a2 * z * z);
        return 20 * std::log10(std::max(1e-12, std::abs(response)));
    }
    double effectiveFilterFrequency(double hz) const { return juce::jlimit(20.0, rate() * .45, hz); }
    juce::Point<float> filterPoint(juce::Rectangle<float> a) const {
        const auto db = 20 * std::log10(double(p.state["resonance_q"]));
        return {frequencyX(effectiveFilterFrequency(double(p.state["frequency_hz"])), a), a.getY() + float((24 - db) / 84) * a.getHeight()};
    }
    void paintFilter(juce::Graphics& g, juce::Rectangle<float> a) {
        frequencyGrid(g, a, false); text(g, "Wet / F: cutoff + resonance", int(a.getX()), 2, int(a.getWidth()));
        if (dirty) {
            curve.clear(); for (int i = 0; i < 180; ++i) {
                const auto hz = 20 * std::pow(upper() / 20, double(i) / 179);
                const auto pt = juce::Point<float>(a.getX() + float(i) / 179 * a.getWidth(), a.getY() + float((24 - juce::jlimit(-60.0, 24.0, filterDb(hz))) / 84) * a.getHeight());
                if (i == 0) curve.startNewSubPath(pt); else curve.lineTo(pt);
            }
            dirty = false;
        }
        const bool lfo = bool(p.state["lfo_enabled"]);
        if (lfo) {
            const double cutoff = double(p.state["frequency_hz"]), extent = std::exp2(2 * double(p.state["lfo_depth"]));
            const auto l = frequencyX(effectiveFilterFrequency(cutoff / extent), a), r = frequencyX(effectiveFilterFrequency(cutoff * extent), a);
            g.setColour(juce::Colour(0xffeceee8)); g.fillRect(juce::Rectangle<float>(l, a.getY(), r - l, a.getHeight()));
        }
        g.setColour(ink); g.strokePath(curve, juce::PathStrokeType(1.6f)); handle(g, filterPoint(a), "F");
        if (a.getWidth() > 250) {
            const auto preview = juce::Rectangle<float>(a.getRight() - 112, a.getBottom() - 36, 100, 24);
            juce::Path wave; for (int i = 0; i <= 100; ++i) {
                const float x = preview.getX() + i;
                const float y = preview.getCentreY() - (lfo ? 1.0f : 0.0f) * float(std::sin(double(i) / 100 * 2 * juce::MathConstants<double>::pi * double(p.state["lfo_hz"]))) * float(double(p.state["lfo_depth"])) * 10;
                if (i == 0) wave.startNewSubPath(x, y); else wave.lineTo(x, y);
            }
            g.setColour(quiet); g.strokePath(wave, juce::PathStrokeType(1)); text(g, "LFO / 1 s guide", int(preview.getX()) - 4, int(preview.getY()) - 17, 116);
        }
    }
    void mouseDown(const juce::MouseEvent& event) override {
        if (!p.valid || !event.mods.isLeftButtonDown()) return;
        const auto a = plot(); if (a.isEmpty()) return; const auto type = p.state["type"].toString();
        selectedHandle = -1; float nearest = 18;
        auto choose = [&](int id, juce::Point<float> point) { const auto d = point.getDistanceFrom(event.position); if (d < nearest) { nearest = d; selectedHandle = id; } };
        if (type == "eq8") {
            if (auto* bands = p.state["bands"].getArray()) for (int i = 0; i < bands->size() && i < 8; ++i) choose(i, bandPoint(bands->getReference(i), a));
            if (selectedHandle >= 0) { p.selectedBand = selectedHandle; p.refreshControls(); }
        } else if (type == "compressor") { choose(0, thresholdPoint(a)); if (double(p.state["threshold_db"]) < 0) choose(1, ratioPoint(a)); }
        else if (type == "delay") { choose(0, delayPoint(a, false)); choose(1, delayPoint(a, true)); frozenHorizon = delayHorizon(); }
        else if (type == "reverb") { choose(0, decayPoint(a)); frozenHorizon = reverbHorizon(); }
        else if (type == "auto_filter") choose(0, filterPoint(a));
        if (selectedHandle < 0) return;
        p.beginGesture();if(p.gestureFailed){p.finishGesture();return;}
        moving = true; changed = false; grabKeyboardFocus();
    }
    void mouseDrag(const juce::MouseEvent& event) override {
        if (!moving || !p.valid) return;
        const auto a = plot(); if (a.isEmpty()) return; const auto type = p.state["type"].toString();
        const auto x = juce::jlimit(0.0, 1.0, double((event.position.x - a.getX()) / a.getWidth()));
        const auto y = juce::jlimit(0.0, 1.0, double((a.getBottom() - event.position.y) / a.getHeight()));
        auto set = [&](int index, double value) { auto& slider = p.sliders[std::size_t(index)]; slider.setValue(value, juce::dontSendNotification); p.applySlider(index); };
        if (type == "eq8") {
            set(0, std::min(20 * std::pow(upper() / 20, x), rate() * .475));
            if (const auto* bands = p.state["bands"].getArray()) if (gainShape(bands->getReference(p.selectedBand))) set(1, (y - .5) * 48);
        } else if (type == "compressor") {
            if (selectedHandle == 0) set(3, -60 + x * 60);
            else { const double t = double(p.state["threshold_db"]); const auto output = -60 + y * 84;
                if (t < 0) set(4, juce::jlimit(1.0, 20.0, -t / std::max(.001, output - double(p.state["makeup_db"]) - t))); }
        } else if (type == "delay") {
            if (selectedHandle == 0) set(9, x * frozenHorizon);
            else if (double(p.state["dry_wet"]) > .001) set(10, y / double(p.state["dry_wet"]) * 100);
        } else if (type == "reverb") set(9, x * frozenHorizon);
        else if (type == "auto_filter") { set(9, effectiveFilterFrequency(20 * std::pow(upper() / 20, x))); set(10, std::pow(10.0, (-60 + y * 84) / 20)); }
        changed = true;p.gestureChanged=true;p.previewGesture();
    }
    void mouseUp(const juce::MouseEvent&) override {
        if (!moving) return;moving=false;p.finishGesture();invalidate();
    }
    bool keyPressed(const juce::KeyPress& key) override {
        if (key == juce::KeyPress::escapeKey && moving) { moving=false;p.cancelGesture();return true; }
        return false;
    }
    Impl& p; juce::Path curve; bool dirty = true, moving = false, changed = false;
    int selectedHandle = -1; double frozenHorizon = 1000;
};
