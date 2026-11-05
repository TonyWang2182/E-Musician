#include "NativeEffectsPanel.h"
#include "UiLanguage.h"
#include "NativeEffects.h"
#include "DeviceControlStyle.h"
#include <complex>
#include <algorithm>
#include <array>
#include <cmath>
#include <juce_dsp/juce_dsp.h>

namespace emusician {
namespace {
const juce::Colour ink(0xff171817), quiet(0xff626560), rule(0xffc6c9c3), paper(0xfffefefd);
juce::Font mono(float size) { return juce::Font(juce::FontOptions(juce::Font::getDefaultMonospacedFontName(), size, juce::Font::plain)); }
juce::var object(std::initializer_list<std::pair<juce::Identifier, juce::var>> fields) {
    auto* o = new juce::DynamicObject; for (const auto& field : fields) o->setProperty(field.first, field.second); return juce::var(o);
}
}

struct NativeEffectsPanel::Impl {
#include "NativeEffectsGraph.inc"
    Impl(NativeEffectsPanel& component, EngineSession& engine, juce::String track, juce::String device,
         std::function<void(const juce::Result&)> callback)
        : owner(component), session(engine), trackId(std::move(track)), deviceId(std::move(device)), report(std::move(callback)), graph(*this) {
        owner.setLookAndFeel(&controlLook);
        for (auto* c : std::initializer_list<juce::Component*>{ &title, &status, &meter, &addEq, &addComp, &addDelay, &addReverb, &addFilter, &filterMode, &filterLfo, &graph, &bandOn, &shape, &bypass, &reset, &compareAButton, &compareBButton, &copyCompare }) owner.addAndMakeVisible(c);
        for (auto* button : { &addEq, &addComp, &addDelay, &addReverb, &addFilter, &filterMode, &filterLfo, &bandOn, &bypass, &reset }) uiButton(*button, button->getButtonText());
        title.setFont(deviceui::labelFont(14,true)); status.setFont(deviceui::labelFont(11)); status.setColour(juce::Label::textColourId, quiet);
        meter.setFont(mono(11)); meter.setColour(juce::Label::textColourId, quiet); meter.setJustificationType(juce::Justification::centredRight);
        meter.setText("GR --", juce::dontSendNotification);
        meter.setTooltip("Measured gain reduction of the wet compressor signal, before makeup and dry/wet mix; unavailable when the device is not processing.");
        addEq.onClick = [this] { add("eq8"); }; addComp.onClick = [this] { add("compressor"); }; addDelay.onClick = [this] { add("delay"); }; addReverb.onClick = [this] { add("reverb"); }; addFilter.onClick = [this] { add("auto_filter"); };
        bypass.setTooltip("Toggle this device in the existing track/master chain. The operation can be undone.");
        bypass.onClick = [this] {
            if (!valid || dragging) return;
            const auto snapshot = session.snapshot();
            const auto result = snapshot.projectId != projectId || (trackId != "master" && snapshot.selectedTrackId != trackId)
                ? juce::Result::fail("Project or track changed; bypass cancelled.")
                : session.execute("set_plugin_enabled", object({{"track_id",trackId},{"plugin_id",deviceId},{"enabled",!deviceEnabled}}), revision);
            if (report) report(result); revision = 0; update(); if (result.failed()) setError(result.getErrorMessage());
        };
        reset.setTooltip("Restore defaults for the selected EQ band, or for this effect. One command, one undo.");
        reset.onClick = [this] {
            if (!valid || dragging) return;
            native_effects::Settings defaults; const auto type = state["type"].toString();
            defaults.eq = type == "eq8"; defaults.delay = type == "delay"; defaults.reverb = type == "reverb"; defaults.autoFilter = type == "auto_filter";
            auto next = native_effects::encode(defaults);
            if (defaults.eq) { auto copy = state.clone(); if (auto* list = copy["bands"].getArray())
                if (selectedBand < list->size()) list->set(selectedBand, next["bands"].getArray()->getReference(selectedBand)); next = std::move(copy); }
            commit(next, revision, projectId);
        };
        { int id = 1; for (const auto* name : {"Bell", "Low shelf", "High shelf", "High pass", "Low pass", "Notch"}) uiComboItem(shape, id++, name); }
        shape.setTooltip("Filter shape of the selected EQ band. Cut and notch shapes do not use the gain control.");
        shape.onChange = [this] {
            if (updating || !valid || dragging) return; auto next = state.clone();
            if (auto* list = next["bands"].getArray()) if (selectedBand < list->size() && shape.getSelectedId() > 0) {
                const char* shapes[] {"bell", "low_shelf", "high_shelf", "high_pass", "low_pass", "notch"};
                list->getReference(selectedBand).getDynamicObject()->setProperty("shape", shapes[shape.getSelectedId() - 1]);
                commit(next, revision, projectId);
            }
        };
        filterMode.onClick = [this] { if(!valid||dragging)return;auto next=state.clone();next.getDynamicObject()->setProperty("mode",state["mode"].toString()=="low_pass"?"high_pass":"low_pass");commit(next,revision,projectId); };
        filterLfo.onClick = [this] { if(!valid||dragging)return;auto next=state.clone();next.getDynamicObject()->setProperty("lfo_enabled",!bool(state["lfo_enabled"]));commit(next,revision,projectId); };
        for (int i = 0; i < 8; ++i) { owner.addAndMakeVisible(bands[std::size_t(i)]); bands[std::size_t(i)].setButtonText(juce::String(i + 1));
            bands[std::size_t(i)].onClick = [this, i] { if (dragging) return; selectedBand = i; refreshControls(); }; }
        bandOn.onClick = [this] { if (!valid || dragging) return; auto next = state.clone(); auto* list = next["bands"].getArray();
            if (!list || selectedBand >= list->size()) return; auto b = list->getReference(selectedBand); b.getDynamicObject()->setProperty("enabled", !bool(b["enabled"])); commit(next, revision, projectId); };
        const std::array<const char*, 14> labels { "frequency", "gain", "Q", "threshold", "ratio", "attack", "release", "makeup", "dry/wet", "delay", "feedback", "dry/wet", "LFO depth", "dry/wet" };
        const std::array<const char*, 14> suffix { " Hz", " dB", "", " dB", ":1", " ms", " ms", " dB", " %", " ms", " %", " %", " %", " %" };
        const std::array<double, 14> low {20, -24, .1, -60, 1, .1, 10, -24, 0, 1, 0, 0, 0, 0}, high {20000, 24, 10, 0, 20, 200, 2000, 24, 100, 2000, 95, 100, 100, 100}, step {1, .1, .01, .1, .1, .1, 1, .1, 1, 1, 1, 1, 1, 1};
        const std::array<double, 14> defaults {1000,0,.7071,-18,4,10,100,0,100,350,35,35,0,100};
        for (int i = 0; i < 14; ++i) {
            auto& slider = sliders[std::size_t(i)]; auto& label = names[std::size_t(i)]; owner.addAndMakeVisible(slider); owner.addAndMakeVisible(label);
            uiLabel(label, labels[std::size_t(i)]); label.setFont(deviceui::labelFont(12)); label.setColour(juce::Label::textColourId, quiet); label.setJustificationType(juce::Justification::centred);
            slider.setRange(low[std::size_t(i)], high[std::size_t(i)], step[std::size_t(i)]);
            deviceui::configureKnob(slider, controlLook, defaults[std::size_t(i)], suffix[std::size_t(i)]);
            slider.setTitle(labels[std::size_t(i)]);
            if (i == 0) slider.setSkewFactorFromMidPoint(1000);
            slider.onDragStart = [this,i] { beginGesture(i); };
            slider.onDragEnd = [this] { finishGesture(); ignoreUntilRelease=false; };
            slider.onEscape=[this,i] { if(!dragging||activeKnob!=i)return false;cancelGesture();ignoreUntilRelease=true;return true; };
            slider.onValueChange = [this, i] { if(updating||!valid||ignoreUntilRelease||gestureFailed)return;applySlider(i);gestureChanged=true;if(dragging)previewGesture();else commit(state,revision,projectId); };
        }
        compareAButton.onClick=[this]{switchComparison(false);};compareBButton.onClick=[this]{switchComparison(true);};
        copyCompare.onClick=[this]{if(!valid||dragging)return;if(comparisonB)compareA=state.clone();else compareB=state.clone();setError(uiText("Copied current settings to the other comparison slot.","已复制到另一比较槽。"));};
        compareAButton.setTooltip("Recall A; changes this device only, with one Undo. Comparison slots last while this panel is open.");
        compareBButton.setTooltip("Recall B; changes this device only, with one Undo. Comparison slots last while this panel is open.");
        copyCompare.setTooltip("Copy current settings to the other comparison slot without changing audio.");
        update();
    }
    ~Impl() {
        if(gestureId.isNotEmpty())session.execute("cancel_native_effect_gesture",object({{"gesture_id",gestureId}}),session.snapshot().revision);
        owner.setLookAndFeel(nullptr);for(auto& slider:sliders)slider.setLookAndFeel(nullptr);
    }
    void beginGesture(int knob=-1){
        if(!valid||dragging)return;activeKnob=knob;dragging=true;gestureFailed=false;ignoreUntilRelease=false;gestureChanged=false;gestureRevision=revision;gestureProject=projectId;
        juce::var result;const auto outcome=session.execute("begin_native_effect_gesture",object({{"track_id",trackId},{"device_id",deviceId}}),revision,&result);
        if(outcome.failed()){gestureFailed=true;setError(outcome.getErrorMessage());return;}gestureId=result["gesture_id"].toString();
    }
    void previewGesture(){
        if(!dragging||gestureFailed||gestureId.isEmpty())return;
        const auto outcome=session.execute("update_native_effect_gesture",object({{"gesture_id",gestureId},{"state",state}}),gestureRevision);
        if(outcome.failed()){gestureFailed=true;setError(outcome.getErrorMessage());}
    }
    void finishGesture(){
        if(!dragging){gestureFailed=false;return;}dragging=false;
        auto outcome=juce::Result::ok();
        if(gestureId.isNotEmpty())outcome=session.execute(gestureFailed?"cancel_native_effect_gesture":"end_native_effect_gesture",object({{"gesture_id",gestureId}}),session.snapshot().revision);
        gestureId.clear();gestureFailed=false;state=juce::var();revision=0;update();if(report)report(outcome);if(outcome.failed())setError(outcome.getErrorMessage());
    }
    void cancelGesture(){
        if(gestureId.isNotEmpty())session.execute("cancel_native_effect_gesture",object({{"gesture_id",gestureId}}),session.snapshot().revision);
        gestureId.clear();dragging=false;gestureFailed=false;graph.moving=false;state=juce::var();revision=0;update();setError(uiText("Parameter edit cancelled.","已取消参数调整。"));
    }
    void switchComparison(bool next){
        if(!valid||dragging||comparisonB==next)return;if(comparisonB)compareB=state.clone();else compareA=state.clone();
        const auto saved=(next?compareB:compareA).clone();if(!saved.isObject())return;const bool previous=comparisonB;comparisonB=next;if(!commit(saved,revision,projectId)){comparisonB=previous;refreshControls();}
    }
    void add(const juce::String& type) {
        const auto s = session.snapshot();
        if (s.projectId != projectId || (trackId != "master" && s.selectedTrackId != trackId)) { setError("Project or track changed. Reopen the effect panel."); return; }
        juce::var output; const auto result = session.execute("add_native_effect", object({ {"track_id",trackId}, {"type",type} }), s.revision, &output);
        if (report) report(result); if (result.failed()) { setError(result.getErrorMessage()); return; }
        deviceId = output["device_id"].toString(); revision = 0; update(); owner.resized();
    }
    void setError(const juce::String& text) {
        const auto message = text.isEmpty() ? uiText("Drag to hear · Shift: fine · Esc: cancel · Release: one Undo", "拖动试听 · Shift细调 · Esc取消 · 松手记一次撤销") : text;
        status.setText(message, juce::dontSendNotification); status.setTooltip(message);
    }
    void update() {
        if (languageRevision != uiLanguageRevision()) { languageRevision = uiLanguageRevision(); refreshUiButtons(owner); owner.repaint(); }
        const auto snapshot = session.snapshot(); if (sampleRate != snapshot.sampleRate) graph.invalidate(); sampleRate = snapshot.sampleRate;
        if (projectId.isEmpty()) projectId = snapshot.projectId;
        if (snapshot.projectId != projectId || (trackId != "master" && snapshot.selectedTrackId != trackId)) { if(dragging)cancelGesture();valid = false; setError("Project or track changed. Reopen this panel."); refreshControls(); return; }
        const bool exists = trackId == "master" || std::any_of(snapshot.tracks.begin(), snapshot.tracks.end(), [&](const auto& t) { return t.id == trackId; });
        if (!exists) { valid = false; setError("Track no longer exists."); refreshControls(); return; }
        targetName=trackId=="master"?juce::String("Master"):juce::String();for(const auto& track:snapshot.tracks)if(track.id==trackId)targetName=track.name;
        if (dragging) return;
        const auto updateEnabledSlot = [&](const auto& slots) { for (const auto& slot : slots) if (slot.id == deviceId) deviceEnabled = slot.enabled; };
        if (trackId == "master") updateEnabledSlot(snapshot.masterPlugins);
        else for (const auto& track : snapshot.tracks) if (track.id == trackId) updateEnabledSlot(track.plugins);
        uiButton(bypass, deviceEnabled ? "on" : "bypassed");
        valid = !snapshot.recording && !snapshot.recordingFinalizing && !snapshot.nativePending;
        if (deviceId.isEmpty()) { revision = snapshot.revision; state = juce::var(); refreshControls(); return; }
        if (snapshot.revision == revision && state.isObject()) { refreshEnabled(); return; }
        juce::var value; auto result = session.execute("get_native_effect", object({ {"track_id",trackId}, {"device_id",deviceId} }), snapshot.revision, &value);
        if (result.failed() || !value["state"].isObject()) { valid = false; state = juce::var(); setError(result.failed() ? result.getErrorMessage() : "Effect state unavailable."); }
        else { state = value["state"]; revision = snapshot.revision; setError({});
            if(compareDevice!=deviceId){spectrumAvailable=false;spectrumSequence=0;compareDevice=deviceId;compareA=state.clone();compareB=state.clone();comparisonB=false;}
            else if(comparisonB)compareB=state.clone();else compareA=state.clone();
        }
        refreshControls();
    }
    void applySlider(int index) {
        auto next = state.clone();
        if (index < 3) { auto* list = next["bands"].getArray(); if (!list || selectedBand >= list->size()) return;
            auto band = list->getReference(selectedBand); if (!band.isObject()) return;
            const char* keys[] = {"frequency", "gain_db", "q"}; band.getDynamicObject()->setProperty(keys[index], sliders[std::size_t(index)].getValue());
        } else if(index<9) { const char* keys[] = {"threshold_db", "ratio", "attack_ms", "release_ms", "makeup_db", "dry_wet"}; const auto value=sliders[std::size_t(index)].getValue(); next.getDynamicObject()->setProperty(keys[index - 3], index==8?value/100.0:value); }
        else if(state["type"].toString()=="auto_filter") {const char* keys[]={"frequency_hz","resonance_q","lfo_hz","lfo_depth","dry_wet"};const auto value=sliders[std::size_t(index)].getValue();next.getDynamicObject()->setProperty(keys[index-9],index>=12?value/100.0:value);}
        else { const char* delayKeys[] = {"delay_ms","feedback","dry_wet"}; const char* reverbKeys[] = {"decay_seconds","damping","dry_wet"};
            const auto value=sliders[std::size_t(index)].getValue(); const auto* key=state["type"].toString()=="reverb"?reverbKeys[index-9]:delayKeys[index-9];
            next.getDynamicObject()->setProperty(key,index==9?value:value/100.0); }
        state = std::move(next); graph.invalidate();
    }
    bool commit(const juce::var& next, std::uint64_t expected, const juce::String& project) {
        const auto snapshot = session.snapshot();
        const auto result = project != snapshot.projectId || (trackId != "master" && trackId != snapshot.selectedTrackId) ? juce::Result::fail("Project or track changed; parameter edit cancelled.")
            : session.execute("set_native_effect", object({ {"track_id",trackId}, {"device_id",deviceId}, {"state",next} }), expected);
        if (report) report(result); state = juce::var(); revision = 0; update();
        if (result.failed()) setError(result.getErrorMessage());return result.wasOk();
    }
    void refreshEnabled() {
        addEq.setEnabled(valid); addComp.setEnabled(valid); addDelay.setEnabled(valid); addReverb.setEnabled(valid); addFilter.setEnabled(valid); filterMode.setEnabled(valid);filterLfo.setEnabled(valid);bandOn.setEnabled(valid);
        for (auto& button : bands) button.setEnabled(valid && !dragging); for (auto& slider : sliders) slider.setEnabled(valid);
        compareAButton.setEnabled(valid&&!dragging);compareBButton.setEnabled(valid&&!dragging);copyCompare.setEnabled(valid&&!dragging);
        bypass.setEnabled(valid && !dragging); reset.setEnabled(valid && !dragging); shape.setEnabled(valid && !dragging);
        if (const auto* list = state["bands"].getArray()) if (selectedBand < list->size()) sliders[1].setEnabled(valid && Graph::gainShape(list->getReference(selectedBand)));
    }
    void refreshControls() {
        updating = true; const auto type = state["type"].toString(); const bool eq = type == "eq8", comp = type == "compressor", delay = type == "delay", reverb = type == "reverb", filter = type == "auto_filter", empty = deviceId.isEmpty();
        const auto prefix=targetName.isEmpty()?juce::String():targetName+" / ";
        title.setText(prefix + (empty ? "Add a built-in effect" : eq ? "EQ Eight / " + juce::String(selectedBand + 1) : comp ? "Compressor" : delay ? "Stereo Delay" : reverb ? "Reverb" : filter ? "Auto Filter" : "Effect unavailable"), juce::dontSendNotification);
        addEq.setVisible(empty); addComp.setVisible(empty); addDelay.setVisible(empty); addReverb.setVisible(empty); addFilter.setVisible(empty); filterMode.setVisible(filter); filterLfo.setVisible(filter);
        graph.setVisible(eq || comp || delay || reverb || filter); bandOn.setVisible(eq); shape.setVisible(eq); meter.setVisible(comp); bypass.setVisible(!empty); reset.setVisible(!empty);
        compareAButton.setVisible(!empty);compareBButton.setVisible(!empty);copyCompare.setVisible(!empty);
        compareAButton.setToggleState(!comparisonB,juce::dontSendNotification);compareBButton.setToggleState(comparisonB,juce::dontSendNotification);
        copyCompare.setButtonText(comparisonB?"B > A":"A > B");
        uiButton(reset, eq ? "reset band" : "reset");
        if(filter){uiButton(filterMode, state["mode"].toString()=="low_pass"?"low pass":"high pass");uiButton(filterLfo, bool(state["lfo_enabled"])?"LFO on":"LFO off");}
        graph.setTitle(comp ? "Compressor static input output curve" : delay ? "Delay echoes guide" : reverb ? "Reverb decay guide" : filter ? "Filter response" : "Equalizer response");
        graph.setDescription("Response curve and optional measured mono output spectrum. Drag a point to hear changes; Escape cancels. Knobs and value boxes provide keyboard alternatives.");
        for (int i = 0; i < 8; ++i) { bands[std::size_t(i)].setVisible(eq); bands[std::size_t(i)].setToggleState(i == selectedBand, juce::dontSendNotification); }
        for (int i = 0; i < 14; ++i) { names[std::size_t(i)].setVisible((i < 3 && eq) || (i >= 3 && i<9 && comp) || (i>=9 && i<12 && (delay || reverb)) || (i>=9&&filter)); sliders[std::size_t(i)].setVisible(names[std::size_t(i)].isVisible()); }
        if (eq) { if (auto* list = state["bands"].getArray()) if (selectedBand < list->size()) { const auto b = list->getReference(selectedBand);
            uiButton(bandOn, bool(b["enabled"]) ? "band on" : "band off");
            sliders[0].setValue(double(b["frequency"]), juce::dontSendNotification); sliders[1].setValue(double(b["gain_db"]), juce::dontSendNotification); sliders[2].setValue(double(b["q"]), juce::dontSendNotification);
            sliders[0].setDoubleClickReturnValue(true, effects::EqSettings().bands[std::size_t(selectedBand)].frequency);
            const auto currentShape = b["shape"].toString(); const char* shapes[] {"bell", "low_shelf", "high_shelf", "high_pass", "low_pass", "notch"};
            shape.setSelectedId(selectedBand == 0 ? 2 : selectedBand == 7 ? 3 : 1, juce::dontSendNotification);
            for (int i = 0; i < 6; ++i) if (currentShape == shapes[i]) shape.setSelectedId(i + 1, juce::dontSendNotification);
        }}
        if (comp) { const char* keys[] = {"threshold_db", "ratio", "attack_ms", "release_ms", "makeup_db", "dry_wet"}; for (int i = 0; i < 6; ++i) sliders[std::size_t(i + 3)].setValue(double(state[keys[i]])*(i==5?100.0:1.0), juce::dontSendNotification); }
        if (delay || reverb) {
            uiLabel(names[9], reverb?"decay":"delay"); uiLabel(names[10], reverb?"damping":"feedback");uiLabel(names[11], "dry/wet");
            sliders[9].setRange(reverb?.1:1.0,reverb?8.0:2000.0,reverb?.01:1.0);sliders[9].setTextValueSuffix(reverb?" s":" ms");
            sliders[9].setSkewFactorFromMidPoint(reverb ? 1.8 : 350); sliders[9].setDoubleClickReturnValue(true,reverb?1.8:350);
            sliders[10].setRange(0,reverb?100:95,1);sliders[10].setTextValueSuffix(" %");sliders[11].setRange(0,100,1);sliders[11].setTextValueSuffix(" %");
            sliders[10].setSkewFactor(1); sliders[11].setSkewFactor(1); sliders[10].setDoubleClickReturnValue(true,35); sliders[11].setDoubleClickReturnValue(true,reverb?25:35);
            const char* delayKeys[] = {"delay_ms","feedback","dry_wet"}; const char* reverbKeys[] = {"decay_seconds","damping","dry_wet"};
            for(int i=0;i<3;++i)sliders[std::size_t(i+9)].setValue(double(state[reverb?reverbKeys[i]:delayKeys[i]])*(i==0?1.0:100.0),juce::dontSendNotification);
        }
        if(filter){const char* keys[]={"frequency_hz","resonance_q","lfo_hz","lfo_depth","dry_wet"};
            const char* labels[]={"cutoff","resonance","LFO rate","LFO depth","dry/wet"};
            const char* suffixes[]={" Hz",""," Hz"," %"," %"};
            const double min[]={20,.5,.05,0,0},max[]={20000,10,20,100,100},step[]={1,.01,.01,1,1};
            for(int i=0;i<5;++i){auto& slider=sliders[std::size_t(i+9)];uiLabel(names[std::size_t(i+9)], labels[i]);slider.setRange(min[i],max[i],step[i]);slider.setTextValueSuffix(suffixes[i]);slider.setValue(double(state[keys[i]])*(i>=3?100.0:1.0),juce::dontSendNotification);}
            sliders[9].setSkewFactorFromMidPoint(1000); sliders[10].setSkewFactorFromMidPoint(2); sliders[11].setSkewFactorFromMidPoint(1);
            const double defaults[] {1000,.7071,1,0,100}; for (int i=0;i<5;++i) sliders[std::size_t(i+9)].setDoubleClickReturnValue(true,defaults[i]);
        }
        for (int i=0;i<14;++i) if (sliders[std::size_t(i)].isVisible()) sliders[std::size_t(i)].setTitle(names[std::size_t(i)].getText());
        updating = false; refreshEnabled(); graph.invalidate(); owner.resized(); owner.repaint();
    }
    void updateSpectrum(){
        if(state["type"].toString()!="eq8"||!valid||!deviceEnabled){spectrumAvailable=false;return;}
        std::array<float,2048> frame{};std::uint64_t sequence=0;
        if(session.nativeEffectSpectrum(projectId,trackId,deviceId,frame,sequence)&&sequence!=spectrumSequence){
            spectrumSequence=sequence;spectrumStale=0;fftData.fill(0);
            for(std::size_t i=0;i<frame.size();++i)fftData[i]=frame[i]*float(.5-.5*std::cos(2*juce::MathConstants<double>::pi*double(i)/2047));
            fft.performFrequencyOnlyForwardTransform(fftData.data());
            const double rate=sampleRate>0?sampleRate:48000;
            for(std::size_t i=0;i<spectrumDb.size();++i){
                const double low=20*std::pow(std::min(20000.0,rate*.49)/20,double(i)/spectrumDb.size());
                const double high=20*std::pow(std::min(20000.0,rate*.49)/20,double(i+1)/spectrumDb.size());
                const int first=juce::jlimit(1,1023,int(std::floor(low*2048/rate))),last=juce::jlimit(first,1023,int(std::ceil(high*2048/rate)));
                float peak=0;for(int bin=first;bin<=last;++bin)peak=juce::jmax(peak,fftData[std::size_t(bin)]);
                spectrumDb[i]=juce::jlimit(-90.0f,0.0f,20*std::log10(juce::jmax(1e-8f,peak*float(2.0/1023.5))));
            }
            spectrumAvailable=true;
        }else if(++spectrumStale>=10)spectrumAvailable=false;
        graph.repaint();
    }
    juce::dsp::FFT fft{11};std::array<float,4096> fftData{};std::array<float,128> spectrumDb{};
    std::uint64_t spectrumSequence=0;int spectrumStale=0,pollTick=0;bool spectrumAvailable=false;
    NativeEffectsPanel& owner; EngineSession& session; juce::String trackId, deviceId, projectId, gestureProject,gestureId,targetName,compareDevice;
    std::function<void(const juce::Result&)> report; juce::var state,compareA,compareB; std::uint64_t revision = 0, gestureRevision = 0; double sampleRate = 0;
    bool comparisonB=false,gestureFailed=false,ignoreUntilRelease=false;
    bool valid = false, updating = false, dragging = false, gestureChanged = false, deviceEnabled = true; int selectedBand = 0,activeKnob=-1;
    unsigned languageRevision = 0;
    juce::Label title, status, meter; juce::TextButton addEq {"add EQ Eight"}, addComp {"add Compressor"}, addDelay {"add Stereo Delay"}, addReverb {"add Reverb"}, addFilter {"add Auto Filter"}, filterMode {"low pass"}, filterLfo {"LFO off"}, bandOn {"band on"};
    std::uint64_t meterSequence = 0; int staleMeterPolls = 0;
    float reductionDb = 0; bool meterAvailable = false;
    juce::TextButton compareAButton{"A"},compareBButton{"B"},copyCompare{"A > B"};
    juce::TextButton bypass {"on"}, reset {"reset"}; juce::ComboBox shape;
    deviceui::ControlLook controlLook;
    std::array<juce::TextButton, 8> bands; std::array<deviceui::Knob, 14> sliders; std::array<juce::Label, 14> names; Graph graph;
};

NativeEffectsPanel::NativeEffectsPanel(EngineSession& session, juce::String track, juce::String device, std::function<void(const juce::Result&)> report)
    : impl(nullptr) { impl = std::make_unique<Impl>(*this, session, std::move(track), std::move(device), std::move(report)); resized(); }
NativeEffectsPanel::~NativeEffectsPanel() { stopTimer(); }
void NativeEffectsPanel::visibilityChanged() {if(!impl)return;if(!isShowing()&&impl->dragging)impl->cancelGesture();if(isVisible()){if(isShowing())impl->update();startTimer(isShowing()?50:1000);}else stopTimer();}
void NativeEffectsPanel::timerCallback() {
    if (!isVisible()) { stopTimer(); return; }
    if(!isShowing()){if(impl->dragging)impl->cancelGesture();startTimer(1000);return;}
    if(getTimerInterval()!=50)startTimer(50);
    if(++impl->pollTick%5==0)impl->update();impl->updateSpectrum();
    if (impl->state["type"].toString() != "compressor") return;
    float value=0;std::uint64_t sequence=0;
    if(impl->session.nativeCompressorMeter(impl->projectId,impl->trackId,impl->deviceId,value,sequence)){
        if(sequence!=impl->meterSequence){impl->meterSequence=sequence;impl->staleMeterPolls=0;}else ++impl->staleMeterPolls;
        if(impl->staleMeterPolls<10){impl->meter.setText("GR -"+juce::String(value,1)+" dB",juce::dontSendNotification);impl->reductionDb=value;impl->meterAvailable=true;impl->graph.repaint();return;}
    }
    impl->meter.setText("GR --",juce::dontSendNotification);impl->meterAvailable=false;impl->graph.repaint();
}
void NativeEffectsPanel::paint(juce::Graphics& g) { g.fillAll(paper); g.setColour(rule); g.drawHorizontalLine(34, 10, float(getWidth() - 10)); }
void NativeEffectsPanel::resized() {
    if (!impl) return; auto& p = *impl; const int width = getWidth(), height = getHeight();
    const auto type = p.state["type"].toString(); const bool eq = type == "eq8", comp = type == "compressor", filter = type == "auto_filter";
    int right=width-12;p.reset.setBounds(right-72,5,72,25);right-=78;p.bypass.setBounds(right-56,5,56,25);right-=62;
    p.copyCompare.setBounds(right-46,5,46,25);right-=50;p.compareBButton.setBounds(right-27,5,27,25);right-=29;p.compareAButton.setBounds(right-27,5,27,25);right-=33;
    if(comp){p.meter.setBounds(right-88,5,88,25);right-=94;}
    p.title.setBounds(12,4,juce::jmax(80,right-18),26);
    p.status.setBounds(12, height - 23, juce::jmax(100,width - 24), 20);
    const std::array<juce::TextButton*,5> addButtons {&p.addEq,&p.addComp,&p.addDelay,&p.addReverb,&p.addFilter};
    const int addColumns = juce::jmax(1, (width - 24) / 164);
    for (int i=0;i<5;++i) addButtons[std::size_t(i)]->setBounds(12+(i%addColumns)*164,52+(i/addColumns)*40,154,32);
    if(eq&&width>=720&&height>=240){
        const int bottom=height-108;p.graph.setBounds(12,39,width-24,bottom-43);
        for(int i=0;i<8;++i)p.bands[std::size_t(i)].setBounds(16+i*28,bottom+6,25,25);
        p.shape.setBounds(16,bottom+40,134,27);p.bandOn.setBounds(156,bottom+40,82,27);
        const int controlsX=juce::jmax(260,width-420),cell=(width-controlsX-12)/3;
        for(int i=0;i<3;++i){p.names[std::size_t(i)].setBounds(controlsX+i*cell,bottom,cell,17);
            p.sliders[std::size_t(i)].setBounds(controlsX+i*cell+4,bottom+17,cell-8,65);
            p.sliders[std::size_t(i)].setTextBoxStyle(juce::Slider::TextBoxBelow,false,juce::jmin(100,cell-8),22);}
        return;
    }
    const int graphWidth = juce::jmax(220, (width-36)/2), x = 12 + graphWidth + 12, controlsWidth = width - x - 12;
    p.graph.setBounds(12,40,graphWidth,juce::jmax(80,height-(eq||filter?94:65)));
    const int bandWidth = juce::jmin(34,graphWidth/8);
    for (int i=0;i<8;++i) p.bands[std::size_t(i)].setBounds(12+i*bandWidth,height-50,bandWidth-4,26);
    p.shape.setBounds(x,height-62,juce::jmax(100,controlsWidth-94),28); p.bandOn.setBounds(x+controlsWidth-86,height-62,86,28);
    p.filterMode.setBounds(12,height-50,112,26); p.filterLfo.setBounds(134,height-50,102,26);
    const int first = eq?0:comp?3:9, count = eq?3:comp?6:filter?5:3;
    const int rows = (comp||filter)?2:1;
    // Reserve EQ shape controls independently of knob height; this also fits
    // the 212 px body used by a 1000x650 window with its Agent sidebar open.
    const int rowHeight = rows==2 ? (height-65)/2 : juce::jmin(eq?122:160,height-(eq?128:88));
    for (int i=0;i<count;++i) {
        const int column=i%3, row=i/3, cellWidth=controlsWidth/3, y=42+row*rowHeight;
        auto& slider=p.sliders[std::size_t(first+i)]; auto& label=p.names[std::size_t(first+i)];
        label.setBounds(x+column*cellWidth,y,cellWidth,17);
        slider.setBounds(x+column*cellWidth+2,y+17,cellWidth-4,rowHeight-18);
        slider.setTextBoxStyle(juce::Slider::TextBoxBelow,false,juce::jmin(100,cellWidth-4),22);
    }
}
juce::Result NativeEffectsPanel::runInteractionSmokeTest(juce::DynamicObject& report, const juce::File& directory) {
    // Only call with an isolated test project. Exercise real commands and views.
    auto& p = *impl; p.update();
    if (!p.valid || !p.deviceId.isEmpty()) return juce::Result::fail("Effect UI fixture needs an empty selected track.");
    const auto initial = p.session.snapshot();
    p.addEq.onClick();
    if (p.deviceId.isEmpty() || p.state["type"].toString() != "eq8") return juce::Result::fail("UI could not add or read an EQ.");
    if (p.trackId == "master") {
        const auto after = p.session.snapshot();
        if (after.masterPlugins.size() != initial.masterPlugins.size() + 1 || after.tracks.size() != initial.tracks.size())
            return juce::Result::fail("Master effect was not added to the master chain.");
        for (std::size_t i = 0; i < after.tracks.size(); ++i)
            if (after.tracks[i].plugins.size() != initial.tracks[i].plugins.size())
                return juce::Result::fail("Master effect changed an ordinary track chain.");
    }
    p.bands[2].onClick(); p.sliders[1].setValue(5.0, juce::sendNotificationSync);
    juce::var result; auto snapshot = p.session.snapshot();
    auto read = p.session.execute("get_native_effect", object({ {"track_id",p.trackId}, {"device_id",p.deviceId} }), snapshot.revision, &result);
    const auto* values = result["state"]["bands"].getArray();
    if (read.failed() || !values || values->size() != 8 || std::abs(double(values->getReference(2)["gain_db"]) - 5.0) > 0.01)
        return juce::Result::fail("EQ slider did not update the selected real band.");
    const auto beforeDrag = snapshot.revision;
    p.sliders[1].onDragStart(); p.sliders[1].setValue(10.0, juce::sendNotificationSync);
    if (p.session.snapshot().revision != beforeDrag) return juce::Result::fail("EQ drag committed before release.");
    const auto unrelated = p.trackId == "master"
        ? p.session.execute("set_master_gain", object({ {"gain_db", -5.0} }), beforeDrag)
        : p.session.execute("rename_track", object({ {"track_id",p.trackId}, {"name","Changed during gesture"} }), beforeDrag);
    if (unrelated.failed()) return juce::Result::fail("Could not create stale gesture fixture.");
    p.sliders[1].onDragEnd(); snapshot = p.session.snapshot();
    read = p.session.execute("get_native_effect", object({ {"track_id",p.trackId}, {"device_id",p.deviceId} }), snapshot.revision, &result);
    values = result["state"]["bands"].getArray();
    if (read.failed() || !values || std::abs(double(values->getReference(2)["gain_db"]) - 5.0) > 0.01)
        return juce::Result::fail("A stale EQ gesture overwrote the current project.");
    {
        const auto version=p.session.snapshot().revision;
        p.sliders[1].onDragStart();p.sliders[1].setValue(6,juce::sendNotificationSync);p.sliders[1].setValue(8,juce::sendNotificationSync);
        read=p.session.execute("get_native_effect",object({{"track_id",p.trackId},{"device_id",p.deviceId}}),version,&result);
        if(read.failed()||p.session.snapshot().revision!=version||std::abs(double(result["state"]["bands"].getArray()->getReference(2)["gain_db"])-5)>.01)
            return juce::Result::fail("Continuous knob preview leaked into committed state or revision.");
        p.sliders[1].keyPressed(juce::KeyPress(juce::KeyPress::escapeKey));p.sliders[1].onDragEnd();
        if(p.session.snapshot().revision!=version||std::abs(double(p.state["bands"].getArray()->getReference(2)["gain_db"])-5)>.01)
            return juce::Result::fail("Knob Escape failed to restore committed state without an Undo step.");
        p.sliders[1].onDragStart();p.sliders[1].setValue(7,juce::sendNotificationSync);p.sliders[1].setValue(9,juce::sendNotificationSync);p.sliders[1].onDragEnd();
        if(p.session.snapshot().revision!=version+1)return juce::Result::fail("One knob gesture did not produce one revision.");
        if(p.session.execute("undo",object({}),p.session.snapshot().revision).failed())return juce::Result::fail("Knob gesture Undo failed.");
        p.revision=0;p.update();if(std::abs(double(p.state["bands"].getArray()->getReference(2)["gain_db"])-5)>.01)return juce::Result::fail("One Undo did not restore the full knob gesture.");
        p.compareBButton.onClick();if(std::abs(double(p.state["bands"].getArray()->getReference(2)["gain_db"]))>.01)return juce::Result::fail("B did not recall the captured comparison.");
        p.compareAButton.onClick();if(std::abs(double(p.state["bands"].getArray()->getReference(2)["gain_db"])-5)>.01)return juce::Result::fail("A did not restore the edited comparison.");
        p.copyCompare.onClick();p.sliders[1].setValue(6,juce::sendNotificationSync);p.compareBButton.onClick();
        if(std::abs(double(p.state["bands"].getArray()->getReference(2)["gain_db"])-5)>.01)return juce::Result::fail("Copy comparison did not preserve its independent captured values.");
        p.compareAButton.onClick();p.sliders[1].setValue(5,juce::sendNotificationSync);
    }
    setSize(1000, 250); if (!getLocalBounds().contains(p.graph.getBounds()) || !getLocalBounds().contains(p.bandOn.getBounds()))
        return juce::Result::fail("EQ controls overflow the compact dock.");
    auto saveImage = [&](const char* name) { juce::MemoryOutputStream bytes; const auto image = createComponentSnapshot(getLocalBounds(), true);
        return image.isValid() && juce::PNGImageFormat().writeImageToStream(image, bytes) && directory.getChildFile(name).replaceWithData(bytes.getData(), bytes.getDataSize()); };
    const auto graphEvent = [&](juce::Point<float> position, juce::Point<float> start, bool moved) {
        const auto now = juce::Time::getCurrentTime();
        return juce::MouseEvent(juce::Desktop::getInstance().getMainMouseSource(), position,
            juce::ModifierKeys(juce::ModifierKeys::leftButtonModifier), 1,0,0,0,0,&p.graph,&p.graph,now,start,now,1,moved);
    };
    const auto knobsFit = [&] {
        for (const auto& slider : p.sliders) if (slider.isVisible()) {
            if (slider.getSliderStyle() != juce::Slider::RotaryVerticalDrag || !getLocalBounds().contains(slider.getBounds())) return false;
            bool readableValue = false;
            for (auto* child : slider.getChildren()) if (const auto* label = dynamic_cast<juce::Label*>(child))
                readableValue = readableValue || (label->isVisible() && label->getText().isNotEmpty() && slider.getLocalBounds().contains(label->getBounds()) && label->getHeight() >= 20);
            if (!readableValue) return false;
        }
        return true;
    };
    p.shape.setSelectedId(4,juce::sendNotificationSync);
    snapshot=p.session.snapshot(); read=p.session.execute("get_native_effect",object({{"track_id",p.trackId},{"device_id",p.deviceId}}),snapshot.revision,&result);
    if (read.failed() || result["state"]["bands"].getArray()->getReference(2)["shape"].toString() != "high_pass" || p.sliders[1].isEnabled())
        return juce::Result::fail("EQ shape did not update the real band or disable its unused gain control.");
    p.reset.onClick();
    if (p.state["bands"].getArray()->getReference(2)["shape"].toString() != "bell" || !p.sliders[1].isEnabled())
        return juce::Result::fail("EQ band reset did not restore the original shape.");
    {
        const auto originalRate=p.sampleRate; p.sampleRate=22050;
        auto lowRateBand=p.state["bands"].getArray()->getReference(2).clone();lowRateBand.getDynamicObject()->setProperty("frequency",20000.0);
        const auto a=p.graph.plot();const auto node=p.graph.bandPoint(lowRateBand,a);
        const bool correct=std::abs(node.x-p.graph.frequencyX(22050*.475,a))<.01f;p.sampleRate=originalRate;
        if(!correct)return juce::Result::fail("EQ node did not follow the DSP cutoff at a low sample rate.");
    }
    p.sliders[1].setValue(5,juce::sendNotificationSync);
    p.bypass.onClick(); if(p.deviceEnabled) return juce::Result::fail("Native effect bypass did not disable the actual slot.");
    p.bypass.onClick(); if(!p.deviceEnabled) return juce::Result::fail("Native effect bypass did not restore the actual slot.");
    setSize(600,250); if(!knobsFit() || !getLocalBounds().contains(p.shape.getBounds()) || !saveImage(p.trackId=="master"?"ui-native-eq-master-compact.png":"ui-native-eq-compact.png"))
        return juce::Result::fail("EQ knobs, shape, or values overflow the 600 px dock.");
    setSize(600,212); if(!knobsFit() || p.sliders[0].getBottom()>=p.shape.getY() || !getLocalBounds().contains(p.bandOn.getBounds())
        || !saveImage(p.trackId=="master"?"ui-native-eq-master-minimum.png":"ui-native-eq-minimum.png"))return juce::Result::fail("EQ controls overlap or overflow the minimum dock.");
    setSize(1000,330);
    if(p.graph.getWidth()<950||p.sliders[0].getY()<p.graph.getBottom())return juce::Result::fail("Expanded EQ does not give the response graph full width with bottom controls.");
    if (!saveImage(p.trackId == "master" ? "ui-native-eq-master-dock.png" : "ui-native-eq-dock.png")) return juce::Result::fail("Could not capture the EQ panel.");
    setSize(1000,250);
    p.deviceId.clear(); p.state = juce::var(); p.update(); p.addComp.onClick();
    if (p.deviceId.isEmpty() || p.state["type"].toString() != "compressor") return juce::Result::fail("UI could not add or read a compressor.");
    p.sliders[3].setValue(-12, juce::sendNotificationSync);
    p.sliders[4].setValue(2, juce::sendNotificationSync); p.sliders[7].setValue(3, juce::sendNotificationSync); snapshot = p.session.snapshot();
    read = p.session.execute("get_native_effect", object({ {"track_id",p.trackId}, {"device_id",p.deviceId} }), snapshot.revision, &result);
    if (read.failed() || std::abs(double(result["state"]["threshold_db"]) + 12) > 0.01
        || std::abs(Impl::Graph::compressorOutputDb(0, double(p.state["threshold_db"]), double(p.state["ratio"]), double(p.state["makeup_db"])) + 3) > 0.001)
        return juce::Result::fail("Compressor controls did not update the real static response.");
    p.sliders[8].setValue(50, juce::sendNotificationSync); snapshot=p.session.snapshot();
    read=p.session.execute("get_native_effect",object({{"track_id",p.trackId},{"device_id",p.deviceId}}),snapshot.revision,&result);
    if(read.failed()||std::abs(double(result["state"]["dry_wet"])-.5)>.001
       ||std::abs(Impl::Graph::compressorOutputDb(-10,-12,4,3,0)-(-10))>.001)
        return juce::Result::fail("Compressor dry/wet control or dry response was incorrect.");
    {
        const auto a=p.graph.plot(); const auto start=p.graph.thresholdPoint(a); const auto end=juce::Point<float>(a.getX()+a.getWidth()*.6f,start.y);
        const auto version=p.session.snapshot().revision;
        p.graph.mouseDown(graphEvent(start,start,false)); p.graph.mouseDrag(graphEvent(end,start,true));
        if(p.session.snapshot().revision!=version || !p.graph.moving) return juce::Result::fail("Compressor graph committed before release.");
        p.graph.keyPressed(juce::KeyPress(juce::KeyPress::escapeKey));
        if(p.session.snapshot().revision!=version || std::abs(double(p.state["threshold_db"])+12)>.01) return juce::Result::fail("Compressor graph Escape did not cancel.");
        p.graph.mouseDown(graphEvent(start,start,false)); p.graph.mouseDrag(graphEvent(end,start,true));p.graph.mouseUp(graphEvent(end,start,true));
        if(std::abs(double(p.state["threshold_db"])+24)>.01) return juce::Result::fail("Compressor graph threshold did not commit on release.");
    }
    {
        p.sliders[3].setValue(-.5,juce::sendNotificationSync);p.sliders[4].setValue(4,juce::sendNotificationSync);
        const auto a=p.graph.plot();const auto start=p.graph.ratioPoint(a);
        const auto end=p.graph.compressorPoint(0,-.5+.5/8.0+double(p.state["makeup_db"]),a);
        p.graph.mouseDown(graphEvent(start,start,false));p.graph.mouseDrag(graphEvent(end,start,true));p.graph.mouseUp(graphEvent(end,start,true));
        if(std::abs(double(p.state["ratio"])-8)>.11)return juce::Result::fail("Ratio graph near a zero-dB threshold incorrectly forced a unity ratio.");
        p.sliders[3].setValue(-24,juce::sendNotificationSync);p.sliders[4].setValue(2,juce::sendNotificationSync);
    }
    setSize(600,250); if(!knobsFit() || !saveImage(p.trackId=="master"?"ui-native-compressor-master-compact.png":"ui-native-compressor-compact.png"))
        return juce::Result::fail("Compressor controls or values overflow the compact dock.");
    setSize(600,212);if(!knobsFit()||p.sliders[8].getBottom()>p.status.getY()
        || !saveImage(p.trackId=="master"?"ui-native-compressor-master-minimum.png":"ui-native-compressor-minimum.png"))return juce::Result::fail("Compressor controls overflow the minimum dock.");
    setSize(1000,250);
    if (!p.graph.isVisible() || !getLocalBounds().contains(p.graph.getBounds()) || p.graph.getRight() >= p.names[3].getX()
        || std::abs(Impl::Graph::compressorOutputDb(-30, -12, 4, 3) - (-27)) > 0.001
        || std::abs(Impl::Graph::compressorOutputDb(0, -12, 4, 3) - (-6)) > 0.001
        || !getLocalBounds().contains(p.sliders[8].getBounds()) || !saveImage(p.trackId == "master" ? "ui-native-compressor-master-dock.png" : "ui-native-compressor-dock.png"))
        return juce::Result::fail("Could not fit or capture the compressor panel.");
    p.deviceId.clear();p.state=juce::var();p.update();p.addDelay.onClick();
    if(p.deviceId.isEmpty()||p.state["type"].toString()!="delay")return juce::Result::fail("UI could not add or read a delay.");
    p.sliders[9].setValue(125,juce::sendNotificationSync);p.sliders[10].setValue(50,juce::sendNotificationSync);p.sliders[11].setValue(40,juce::sendNotificationSync);
    snapshot=p.session.snapshot();read=p.session.execute("get_native_effect",object({{"track_id",p.trackId},{"device_id",p.deviceId}}),snapshot.revision,&result);
    if(read.failed()||std::abs(double(result["state"]["delay_ms"])-125)>.001||std::abs(double(result["state"]["feedback"])-.5)>.001
       ||std::abs(double(result["state"]["dry_wet"])-.4)>.001||!getLocalBounds().contains(p.sliders[11].getBounds()))
        return juce::Result::fail("Delay UI controls did not update the real device.");
    {
        const auto a=p.graph.plot(); const auto start=p.graph.delayPoint(a,false); const auto end=juce::Point<float>(a.getX()+a.getWidth()*.25f,start.y);
        const auto version=p.session.snapshot().revision;p.graph.mouseDown(graphEvent(start,start,false));p.graph.mouseDrag(graphEvent(end,start,true));
        if(p.session.snapshot().revision!=version) return juce::Result::fail("Delay graph committed before release.");
        p.graph.mouseUp(graphEvent(end,start,true));if(std::abs(double(p.state["delay_ms"])-250)>.01)return juce::Result::fail("Delay graph time handle did not update the device.");
    }
    setSize(600,250);if(!knobsFit()||!p.graph.isVisible()||!saveImage(p.trackId=="master"?"ui-native-delay-master-compact.png":"ui-native-delay-compact.png"))return juce::Result::fail("Delay graph or knobs did not fit.");
    setSize(600,212);if(!knobsFit()||!getLocalBounds().contains(p.graph.getBounds()))return juce::Result::fail("Delay controls overflow the minimum dock.");setSize(1000,250);
    if(!saveImage(p.trackId=="master"?"ui-native-delay-master-dock.png":"ui-native-delay-dock.png"))return juce::Result::fail("Could not capture delay panel.");
    p.deviceId.clear();p.state=juce::var();p.update();p.addReverb.onClick();
    if(p.deviceId.isEmpty()||p.state["type"].toString()!="reverb")return juce::Result::fail("UI could not add or read a reverb.");
    p.sliders[9].setValue(2.5,juce::sendNotificationSync);p.sliders[10].setValue(40,juce::sendNotificationSync);p.sliders[11].setValue(30,juce::sendNotificationSync);
    snapshot=p.session.snapshot();read=p.session.execute("get_native_effect",object({{"track_id",p.trackId},{"device_id",p.deviceId}}),snapshot.revision,&result);
    if(read.failed()||std::abs(double(result["state"]["decay_seconds"])-2.5)>.001||std::abs(double(result["state"]["damping"])-.4)>.001
       ||std::abs(double(result["state"]["dry_wet"])-.3)>.001||!getLocalBounds().contains(p.sliders[11].getBounds()))
        return juce::Result::fail("Reverb UI controls did not update the real device.");
    {
        const auto a=p.graph.plot(); const auto start=p.graph.decayPoint(a);const auto end=juce::Point<float>(a.getX()+a.getWidth()*.5f,start.y);
        p.graph.mouseDown(graphEvent(start,start,false));p.graph.mouseDrag(graphEvent(end,start,true));p.graph.mouseUp(graphEvent(end,start,true));
        if(std::abs(double(p.state["decay_seconds"])-1.5)>.01)return juce::Result::fail("Reverb decay handle did not update the device.");
    }
    setSize(600,250);if(!knobsFit()||!p.graph.isVisible()||!saveImage(p.trackId=="master"?"ui-native-reverb-master-compact.png":"ui-native-reverb-compact.png"))return juce::Result::fail("Reverb graph or knobs did not fit.");
    setSize(600,212);if(!knobsFit()||!getLocalBounds().contains(p.graph.getBounds()))return juce::Result::fail("Reverb controls overflow the minimum dock.");setSize(1000,250);
    if(!saveImage(p.trackId=="master"?"ui-native-reverb-master-dock.png":"ui-native-reverb-dock.png"))return juce::Result::fail("Could not capture reverb panel.");
    p.deviceId.clear();p.state=juce::var();p.update();p.addFilter.onClick();
    if(p.deviceId.isEmpty()||p.state["type"].toString()!="auto_filter")return juce::Result::fail("UI could not add or read auto filter.");
    p.filterMode.onClick();p.filterLfo.onClick();p.sliders[9].setValue(2000,juce::sendNotificationSync);p.sliders[12].setValue(50,juce::sendNotificationSync);
    snapshot=p.session.snapshot();read=p.session.execute("get_native_effect",object({{"track_id",p.trackId},{"device_id",p.deviceId}}),snapshot.revision,&result);
    if(read.failed()||result["state"]["mode"].toString()!="high_pass"||!bool(result["state"]["lfo_enabled"])
       ||std::abs(double(result["state"]["frequency_hz"])-2000)>.001||std::abs(double(result["state"]["lfo_depth"])-.5)>.001
       ||!getLocalBounds().contains(p.sliders[13].getBounds()))return juce::Result::fail("Auto filter UI did not update the device.");
    {
        const auto a=p.graph.plot(); const auto start=p.graph.filterPoint(a);const auto end=juce::Point<float>(p.graph.frequencyX(4000,a),a.getY()+a.getHeight()*(24.0f-3.0f)/84.0f);
        p.graph.mouseDown(graphEvent(start,start,false));p.graph.mouseDrag(graphEvent(end,start,true));p.graph.mouseUp(graphEvent(end,start,true));
        if(std::abs(double(p.state["frequency_hz"])-4000)>1 || std::abs(double(p.state["resonance_q"])-1.41)>.02)return juce::Result::fail("Filter cutoff/resonance graph did not update the device.");
    }
    {
        auto previousState=p.state;const auto previousRate=p.sampleRate;p.state=p.state.clone();
        p.state.getDynamicObject()->setProperty("frequency_hz",20000.0);p.state.getDynamicObject()->setProperty("resonance_q",10.0);p.sampleRate=22050;
        const auto a=p.graph.plot();const auto node=p.graph.filterPoint(a);
        const bool correct=std::abs(node.x-p.graph.frequencyX(22050*.45,a))<.01f && std::abs(p.graph.filterDb(22050*.45)-20)<.001
            && p.graph.effectiveFilterFrequency(20000*4)==22050*.45;
        p.state=previousState;p.sampleRate=previousRate;p.graph.invalidate();
        if(!correct)return juce::Result::fail("Filter node/LFO extent did not follow the DSP cutoff at a low sample rate.");
    }
    setSize(600,250);if(!knobsFit()||!p.graph.isVisible()||!saveImage(p.trackId=="master"?"ui-native-filter-master-compact.png":"ui-native-filter-compact.png"))return juce::Result::fail("Filter graph or knobs did not fit.");
    setSize(600,212);if(!knobsFit()||p.sliders[13].getBottom()>p.status.getY()||!getLocalBounds().contains(p.filterMode.getBounds())
        ||!saveImage(p.trackId=="master"?"ui-native-filter-master-minimum.png":"ui-native-filter-minimum.png"))return juce::Result::fail("Filter controls overflow the minimum dock.");setSize(1000,250);
    if(!saveImage(p.trackId=="master"?"ui-native-filter-master-dock.png":"ui-native-filter-dock.png"))return juce::Result::fail("Could not capture auto filter panel.");
    p.deviceId.clear();p.state=juce::var();p.update();p.addDelay.onClick();
    if(p.state["type"].toString()!="delay"||p.sliders[9].getMaximum()!=2000||p.sliders[10].getMaximum()!=95
       ||p.sliders[11].getMaximum()!=100||p.sliders[9].getTextValueSuffix()!=" ms"||p.sliders[10].getTextValueSuffix()!=" %"||p.sliders[11].getTextValueSuffix()!=" %")
        return juce::Result::fail("Switching auto filter to delay retained incorrect slider ranges or units.");
    p.sliders[11].setValue(60,juce::sendNotificationSync);
    if(std::abs(double(p.state["dry_wet"])-.6)>.001)return juce::Result::fail("Delay mix was not set after switching from auto filter.");
    p.deviceId.clear();p.state=juce::var();p.update();p.addReverb.onClick();
    if(p.state["type"].toString()!="reverb"||p.sliders[9].getMaximum()!=8||p.sliders[10].getMaximum()!=100
       ||p.sliders[11].getMaximum()!=100||p.sliders[9].getTextValueSuffix()!=" s"||p.sliders[10].getTextValueSuffix()!=" %"||p.sliders[11].getTextValueSuffix()!=" %")
        return juce::Result::fail("Switching to reverb retained incorrect slider ranges or units.");
    report.setProperty(p.trackId == "master" ? "native_effect_master_ui_add_and_adjust" : "native_effect_ui_add_and_adjust", true);
    report.setProperty(p.trackId == "master" ? "native_effect_master_knobs_graphs_shape_bypass" : "native_effect_knobs_graphs_shape_bypass", true);
    report.setProperty(p.trackId == "master" ? "native_effect_master_continuous_escape_ab" : "native_effect_continuous_escape_ab", true);
    return juce::Result::ok();
}
}
