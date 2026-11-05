#pragma once

#include "EngineSession.h"
#include <functional>
#include <memory>
#include <vector>

namespace emusician {

// A view of the authoritative ordered plug-in slots, never a second model.
class DeviceChainStrip final : public juce::Component {
public:
    using Slot = EngineSession::PluginSlotSnapshot;
    std::function<void(const juce::String&, const Slot&)> onSelect;
    std::function<void(const juce::String&, const juce::String&)> onAdd;
    std::function<void(const juce::String&)> onBrowse;

    DeviceChainStrip() {
        for (auto* c : std::initializer_list<juce::Component*>{&previous,&next,&viewport,&sampler,&rack,&eq,&compressor,&delay,&browse}) addAndMakeVisible(c);
        viewport.setViewedComponent(&content, false);
        viewport.setScrollBarsShown(false, false);
        previous.setTooltip("Previous device in signal order");
        next.setTooltip("Next device in signal order");
        previous.onClick = [this] { step(-1); };
        next.onClick = [this] { step(1); };
        sampler.onClick = [this] { add("sampler"); };
        rack.onClick = [this] { add("drum_rack"); };
        eq.onClick = [this] { add("eq8"); };
        compressor.onClick = [this] { add("compressor"); };
        delay.onClick = [this] {
            juce::PopupMenu menu; menu.addItem(1,"Stereo Delay"); menu.addItem(2,"Stereo Reverb"); menu.addItem(3,"Auto Filter");
            const auto project=projectId, target=trackId;
            menu.showMenuAsync(juce::PopupMenu::Options().withTargetComponent(&delay), [safe=juce::Component::SafePointer<DeviceChainStrip>(this),project,target](int choice) {
                if(!safe || safe->projectId!=project || safe->trackId!=target)return;
                if(choice==1)safe->add("delay"); else if(choice==2)safe->add("reverb"); else if(choice==3)safe->add("auto_filter");
            });
        };
        browse.onClick = [this] { if (onBrowse && trackId.isNotEmpty()) onBrowse(trackId); };
        sampler.setTooltip("Add the built-in sampler to the selected MIDI track");
        rack.setTooltip("Add the built-in drum rack to the selected MIDI track");
        eq.setTooltip("Add a built-in eight-band EQ");
        compressor.setTooltip("Add a built-in compressor");
        delay.setTooltip("Add a built-in delay, reverb or auto filter");
        browse.setTooltip("Browse installed VST plug-ins");
        setTitle("Device chain and built-in devices");
    }
    ~DeviceChainStrip() override { viewport.setViewedComponent(nullptr, false); }

    void update(const juce::String& project, const juce::String& target, const juce::String& name,
                const std::vector<Slot>& values, const juce::String& selected,
                bool instrumentTrack, bool canEdit) {
        juce::String signature = project + "\n" + target;
        for (const auto& slot : values) signature += "\n" + slot.id + "/" + slot.name + "/" + slot.format + "/" + slot.identifier + (slot.isInstrument ? "I" : "E") + (slot.enabled ? "+" : "-") + (slot.missing ? "?" : "");
        projectId=project; trackId=target; trackName=name; selectedId=selected;
        if (signature != identity) {
            identity=std::move(signature); slots=values; buttons.clear();
            for (const auto& slot : slots) {
                auto button=std::make_unique<juce::TextButton>((slot.enabled ? "" : "[off] ") + slot.name + (slot.missing ? " [missing]" : ""));
                button->setClickingTogglesState(false); button->setToggleState(slot.id==selectedId, juce::dontSendNotification);
                button->setTooltip(slot.missing ? "Plug-in missing; open the device list to manage it." : "Open " + slot.name + " in signal order");
                button->setEnabled(!slot.missing);
                button->onClick=[this,id=slot.id] { select(id); };
                content.addAndMakeVisible(*button); buttons.push_back(std::move(button));
            }
            resized();
        }
        for (std::size_t i=0;i<buttons.size();++i) buttons[i]->setToggleState(slots[i].id==selectedId,juce::dontSendNotification);
        const bool hasTarget = target.isNotEmpty();
        sampler.setEnabled(canEdit && hasTarget && instrumentTrack);
        rack.setEnabled(canEdit && hasTarget && instrumentTrack);
        eq.setEnabled(canEdit && hasTarget); compressor.setEnabled(canEdit && hasTarget); delay.setEnabled(canEdit && hasTarget);
        browse.setEnabled(canEdit && hasTarget);
        previous.setEnabled(!slots.empty()); next.setEnabled(!slots.empty());
        repaint();
    }
    void resized() override {
        auto chain=getLocalBounds();
        auto catalog=chain.removeFromRight(440);
        for (auto* button : {&sampler,&rack,&eq,&compressor,&delay,&browse}) {
            const int width=button==&sampler?78:button==&rack?88:button==&eq?55:button==&compressor?82:button==&delay?70:67;
            button->setBounds(catalog.removeFromLeft(width).reduced(2));
        }
        previous.setBounds(chain.removeFromLeft(30).reduced(2)); next.setBounds(chain.removeFromRight(30).reduced(2));
        viewport.setBounds(chain.reduced(2,1));
        int x=0; for (auto& button:buttons) { const int w=juce::jlimit(92,180,button->getButtonText().length()*8+24); button->setBounds(x,0,w,27); x+=w+4; }
        content.setSize(juce::jmax(x,viewport.getWidth()),27);
    }
    void paint(juce::Graphics& g) override {
        g.fillAll(juce::Colour(0xfffefefd));
        g.setColour(juce::Colour(0xffc6c9c3)); g.drawHorizontalLine(getHeight()-1,0,float(getWidth()));
        if (slots.empty()) { g.setColour(juce::Colour(0xff626560)); g.setFont(12.0f); g.drawText(trackId.isEmpty()?"Select a track":"No devices on " + trackName, 37,3,juce::jmax(0,getWidth()-514),25,juce::Justification::centredLeft,true); }
    }
    int deviceCount() const noexcept { return int(slots.size()); }
    juce::String selectedForTest() const { return selectedId; }
    void selectForTest(const juce::String& id) { select(id); }
    void stepForTest(int delta) { step(delta); }

private:
    void add(const juce::String& type) { if (onAdd && trackId.isNotEmpty()) onAdd(trackId,type); }
    void select(const juce::String& id) {
        for (const auto& slot : slots) if (slot.id==id && !slot.missing) {
            selectedId=id; for (std::size_t i=0;i<slots.size();++i) buttons[i]->setToggleState(slots[i].id==id,juce::dontSendNotification);
            if(onSelect)onSelect(trackId,slot); return;
        }
    }
    void step(int delta) {
        if (slots.empty()) return;
        int current=-1; for(int i=0;i<int(slots.size());++i) if(slots[std::size_t(i)].id==selectedId)current=i;
        const int first=current<0 ? (delta>0?0:int(slots.size())-1) : juce::jlimit(0,int(slots.size())-1,current+delta);
        for(int i=first;i>=0&&i<int(slots.size());i+=delta) if(!slots[std::size_t(i)].missing) {
            const auto bounds=buttons[std::size_t(i)]->getBounds();
            viewport.setViewPosition(juce::jlimit(0,juce::jmax(0,content.getWidth()-viewport.getWidth()),bounds.getX() - viewport.getWidth()/2 + bounds.getWidth()/2),0);
            select(slots[std::size_t(i)].id); return;
        }
    }
    juce::String projectId, trackId, trackName, selectedId, identity;
    std::vector<Slot> slots;
    std::vector<std::unique_ptr<juce::TextButton>> buttons;
    juce::TextButton previous { "<" }, next { ">" }, sampler { "+ Sampler" }, rack { "+ Rack" }, eq { "+ EQ" }, compressor { "+ Comp" }, delay { "+ FX" }, browse { "+ VST" };
    juce::Viewport viewport;
    juce::Component content;
};
}
