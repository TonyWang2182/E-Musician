#pragma once
#include "EngineSession.h"
#include "UiDesign.h"
#include "UiLanguage.h"

namespace emusician {
// Catalogue and project assets are read-only projections. Activation is routed
// back through MainComponent's normal command/import path.
class WorkspaceBrowser final : public juce::Component, private juce::ListBoxModel {
public:
    struct Item { juce::String kind, id, name, detail; };
    WorkspaceBrowser() : list("Library", this) {
        addAndMakeVisible(search); addAndMakeVisible(category); addAndMakeVisible(list); addAndMakeVisible(open);
        search.setTextToShowWhenEmpty("Search library", design::secondary);
        search.setFont(design::labelFont(13)); search.onTextChange=[this]{filter();};
        category.addItem("All",1);category.addItem("Instruments",2);category.addItem("Audio effects",3);
        category.addItem("Plug-ins",4);category.addItem("Project audio",5);category.setSelectedId(1);
        category.onChange=[this]{filter();};
        list.setColour(juce::ListBox::backgroundColourId,design::panel);list.setRowHeight(42);
        open.setButtonText("Open / add");open.onClick=[this]{activate(list.getSelectedRow());};
        search.setTitle("Search library");category.setTitle("Library category");
        list.setTooltip("Double-click or press Enter to add a device, or locate an audio clip in this project.");
    }
    ~WorkspaceBrowser() override {list.setModel(nullptr);}
    std::function<void(const Item&)> onActivate;
    void update(const EngineSession::Snapshot& state) {
        std::uint64_t signature=0;for(const auto& p:state.pluginCatalog){signature=signature*31+std::uint64_t(p.id.hashCode64());signature=signature*31+std::uint64_t(p.name.hashCode64());signature=signature*31+std::uint64_t(p.format.hashCode64());}
        if (project==state.projectId && revision==state.revision && catalogSignature==signature && language==uiLanguageRevision())return;
        project=state.projectId;revision=state.revision;catalogSignature=signature;language=uiLanguageRevision();
        search.setTextToShowWhenEmpty(uiText("Search library", "搜索音色与装置"),design::secondary);
        const auto selected=category.getSelectedId();category.clear(juce::dontSendNotification);
        category.addItem(uiText("All", "全部"),1);category.addItem(uiText("Instruments", "乐器"),2);
        category.addItem(uiText("Audio effects", "音频效果"),3);category.addItem(uiText("Plug-ins", "插件"),4);
        category.addItem(uiText("Project audio", "工程音频"),5);category.setSelectedId(selected,juce::dontSendNotification);
        open.setButtonText(uiText("Open / add", "打开 / 添加"));items.clear();
        items.push_back({"instrument","sampler","Sampler",uiText("Sample instrument", "采样乐器")});
        items.push_back({"instrument","drum_rack","Drum Rack",uiText("16 pads", "16 鼓垫")});
        for (const auto& pair : std::initializer_list<std::pair<const char*, const char*>>{{"eq8","EQ Eight"},{"compressor","Compressor"},{"delay","Delay"},{"reverb","Reverb"},{"auto_filter","Auto Filter"}})
            items.push_back({"effect",pair.first,pair.second,uiText("Native effect", "原生效果器")});
        for(const auto& plugin:state.pluginCatalog)items.push_back({"plugin",plugin.id,plugin.name,plugin.format});
        for(const auto& track:state.tracks)for(const auto& clip:track.clips)if(clip.kind=="audio")
            items.push_back({"clip",clip.id,clip.source.getFileName(),track.name+" / "+juce::String(clip.timelineStart,1)+"s · "+juce::String(clip.duration,1)+"s"});
        items.push_back({"browse","plugins",uiText("Manage plug-ins…", "管理插件…"),uiText("Scan / folders", "扫描 / 文件夹")});
        items.push_back({"browse","audio",uiText("Import audio…", "导入音频…"),"WAV / MP3"});
        filter();
    }
    void paint(juce::Graphics& g) override {
        g.fillAll(design::panel);g.setColour(design::rule);g.drawVerticalLine(getWidth()-1,0,float(getHeight()));
        g.setColour(design::ink);g.setFont(design::labelFont(14,true));g.drawText(uiText("Library", "资源库"),10,8,getWidth()-20,22,juce::Justification::centredLeft);
    }
    void resized() override {search.setBounds(9,38,getWidth()-18,28);category.setBounds(9,74,getWidth()-18,28);open.setBounds(9,getHeight()-39,getWidth()-18,30);list.setBounds(0,111,getWidth()-1,juce::jmax(0,getHeight()-158));}
    void focusSearch(){search.grabKeyboardFocus();search.selectAll();}
    static juce::Result runActivationLifetimeSmoke(juce::DynamicObject& report) {
        auto browser = std::make_unique<WorkspaceBrowser>();
        EngineSession::Snapshot state; state.projectId = "browser-lifetime-fixture"; state.revision = 1;
        EngineSession::PluginDescriptorSnapshot plugin; plugin.id = "fixture-plugin-id"; plugin.name = "Fixture plugin"; plugin.format = "VST3";
        state.pluginCatalog.push_back(plugin); browser->update(state);
        int row = -1;
        for (int i = 0; i < int(browser->filtered.size()); ++i) if (browser->filtered[std::size_t(i)].id == plugin.id) row = i;
        if (row < 0) return juce::Result::fail("Browser lifetime fixture plugin was not found.");
        bool rebuilt = false, survivedDestruction = false;
        browser->onActivate = [&](const Item& item) {
            ++state.revision; state.pluginCatalog.clear(); browser->update(state);
            rebuilt = item.kind == "plugin" && item.id == plugin.id && item.name == plugin.name;
            browser->onActivate = {}; browser.reset();
            survivedDestruction = item.kind == "plugin" && item.id == plugin.id;
        };
        browser->activate(row);
        report.setProperty("library_activation_survives_catalog_rebuild", rebuilt);
        report.setProperty("library_activation_survives_callback_and_browser_destruction", survivedDestruction && !browser);
        return rebuilt && survivedDestruction && !browser ? juce::Result::ok()
            : juce::Result::fail("Library activation lost the item or callback while rebuilding/destroying the browser.");
    }
private:
    int getNumRows() override{return int(filtered.size());}
    void paintListBoxItem(int row,juce::Graphics& g,int width,int height,bool selected) override {
        if(row<0||row>=int(filtered.size()))return;const auto& item=filtered[std::size_t(row)];
        if(selected){g.setColour(design::accent);g.fillRect(3,1,width-6,height-2);}
        g.setColour(design::ink);g.setFont(design::labelFont(13,selected));g.drawFittedText(item.name,12,3,width-24,20,juce::Justification::centredLeft,1);
        g.setColour(design::secondary);g.setFont(design::labelFont(11));g.drawFittedText(item.detail,12,23,width-24,16,juce::Justification::centredLeft,1);
    }
    void listBoxItemDoubleClicked(int row,const juce::MouseEvent&) override{activate(row);}
    void returnKeyPressed(int row) override{activate(row);}
    juce::var getDragSourceDescription(const juce::SparseSet<int>& rows) override {
        if(rows.size()!=1||rows[0]<0||rows[0]>=int(filtered.size()))return {};
        const auto& item=filtered[std::size_t(rows[0])];if(item.kind=="browse"||item.kind=="clip")return {};
        auto* description=new juce::DynamicObject();description->setProperty("emusician_library",true);
        description->setProperty("kind",item.kind);description->setProperty("id",item.id);return juce::var(description);
    }
    void selectedRowsChanged(int row) override{open.setEnabled(row>=0&&row<int(filtered.size()));}
    void activate(int row){
        if(row<0||row>=int(filtered.size())||!onActivate)return;
        // Adding a device can synchronously rebuild the catalogue, replace this
        // callback, or close the browser. Both arguments must outlive that work.
        const auto item=filtered[std::size_t(row)];const auto callback=onActivate;
        callback(item);
    }
    void filter(){
        const auto selected=list.getSelectedRow();juce::String selectedId;
        if(selected>=0&&selected<int(filtered.size()))selectedId=filtered[std::size_t(selected)].kind+":"+filtered[std::size_t(selected)].id;
        filtered.clear();const auto query=search.getText().trim();const auto cat=category.getSelectedId();
        for(const auto& item:items){
            const bool match=cat==1||(cat==2&&item.kind=="instrument")||(cat==3&&item.kind=="effect")||(cat==4&&(item.kind=="plugin"||item.id=="plugins"))||(cat==5&&(item.kind=="clip"||item.id=="audio"));
            if(match&&(query.isEmpty()||(item.name+" "+item.detail).containsIgnoreCase(query)))filtered.push_back(item);
        }
        list.deselectAllRows();list.updateContent();
        for(std::size_t i=0;i<filtered.size();++i)if(filtered[i].kind+":"+filtered[i].id==selectedId)list.selectRow(int(i));
        open.setEnabled(list.getSelectedRow()>=0);list.repaint();
    }
    juce::TextEditor search;juce::ComboBox category;juce::ListBox list;juce::TextButton open;
    std::vector<Item> items,filtered;juce::String project;std::uint64_t revision=~std::uint64_t(0),catalogSignature=0;unsigned language=~0u;
};
class DockDivider final : public juce::Component {
public:
    DockDivider(){setMouseCursor(juce::MouseCursor::UpDownResizeCursor);}
    std::function<void(int,bool)> onDrag;
    void paint(juce::Graphics& g) override{g.setColour(isMouseOverOrDragging()?design::focus:design::rule);g.fillRect(0,getHeight()/2,getWidth(),1);}
    void mouseDown(const juce::MouseEvent& e) override{origin=e.getScreenY();}
    void mouseDrag(const juce::MouseEvent& e) override{if(onDrag)onDrag(e.getScreenY()-origin,false);}
    void mouseUp(const juce::MouseEvent& e) override{if(onDrag)onDrag(e.getScreenY()-origin,true);}
private:int origin=0;
};
// A bounded, cached picture of actual clips, never a second musical model.
class ProjectOverview final : public juce::Component {
public:
    std::function<void(double)> onReveal;
    void update(const EngineSession::Snapshot& s, juce::Range<double> visible) {
        if (project != s.projectId || revision != s.revision) {
            project=s.projectId;revision=s.revision;duration=juce::jmax(8.0,s.duration);blocks.clear();
            const auto count=juce::jmax(1,int(s.tracks.size()));int row=0;
            for(const auto& t:s.tracks){for(const auto& c:t.clips)blocks.push_back({c.timelineStart,c.duration,float(row)/count,1.0f/count,design::trackColour(t.colour)});++row;}
            rebuild();repaint();
        }
        if(view != visible){view=visible;repaint();}
    }
    void paint(juce::Graphics& g) override {
        g.fillAll(design::panel);const auto area=getLocalBounds().toFloat().reduced(1);
        if(cache.isValid())g.drawImageAt(cache,0,0);
        const auto a=juce::jlimit(0.0,1.0,view.getStart()/duration),b=juce::jlimit(a,1.0,view.getEnd()/duration);
        g.setColour(design::ink.withAlpha(.7f));g.drawRect(juce::Rectangle<float>(area.getX()+float(a)*area.getWidth(),area.getY(),juce::jmax(2.0f,float(b-a)*area.getWidth()),area.getHeight()),1);
    }
    void mouseDown(const juce::MouseEvent& e) override{reveal(e);}
    void mouseDrag(const juce::MouseEvent& e) override{reveal(e);}
    void resized() override{rebuild();}
private:
    void rebuild(){
        if(getWidth()<1||getHeight()<1){cache={};return;}
        cache=juce::Image(juce::Image::ARGB,getWidth(),getHeight(),true);juce::Graphics g(cache);const auto area=getLocalBounds().toFloat().reduced(1);
        for(const auto& b:blocks){g.setColour(b.colour.withAlpha(.75f));g.fillRect(area.getX()+float(b.start/duration)*area.getWidth(),area.getY()+b.row*area.getHeight(),juce::jmax(1.0f,float(b.length/duration)*area.getWidth()),juce::jmax(1.0f,b.height*area.getHeight()));}
    }
    void reveal(const juce::MouseEvent& e){if(onReveal)onReveal(juce::jlimit(0.0,1.0,double(e.x)/juce::jmax(1,getWidth()))*duration);}
    struct Block{double start,length;float row,height;juce::Colour colour;};
    std::vector<Block> blocks;juce::Image cache;juce::String project;std::uint64_t revision=~std::uint64_t(0);double duration=8;juce::Range<double> view;
};
}
