#include "GenerationPanel.h"
#include "UiDesign.h"
#include "UiLanguage.h"
#include <cmath>
#include <limits>

namespace emusician {
namespace {
juce::var generationObject(std::initializer_list<std::pair<juce::Identifier,juce::var>> values)
{auto* data=new juce::DynamicObject();for(const auto& [key,value]:values)data->setProperty(key,value);return data;}
bool finishedGeneration(const juce::String& s)
{return s=="ready"||s=="applied"||s=="failed"||s=="cancelled"||s=="stale"||s=="conflict"||s=="completed";}
}
struct GenerationPanel::Impl {
    GenerationPanel& owner;EngineSession& session;
    juce::Label title,promptLabel,lyricsLabel,durationLabel,seedLabel,context,status;
    juce::TextEditor prompt,lyrics,duration,seed;
    juce::TextButton run,cancel,preview,stop,add;
    juce::ComboBox history,model;
    juce::StringArray modelIds;juce::Array<juce::var> providers;
    juce::String jobId,resultId,acceptId,projectId,lastState,actionError,previewJobId,previewState;
    std::uint64_t resultRevision=std::numeric_limits<std::uint64_t>::max();
    juce::var result;juce::StringArray historyIds;
    juce::Rectangle<int> waveBounds;bool configured=false,previewing=false;int capabilityCountdown=0;
    Impl(GenerationPanel& panel,EngineSession& engine):owner(panel),session(engine){
        for(auto* c:std::initializer_list<juce::Component*>{&title,&promptLabel,&lyricsLabel,&durationLabel,&seedLabel,&context,&status,&prompt,&lyrics,&duration,&seed,&run,&cancel,&preview,&stop,&add,&history,&model})owner.addAndMakeVisible(c);
        model.setName("Generation model");model.onChange=[this]{actionError.clear();const int index=model.getSelectedId()-1;configured=index>=0&&index<providers.size()&&bool(providers[index]["available"]);};
        title.setFont(design::labelFont(15,true));context.setFont(design::numberFont(11));status.setFont(design::labelFont(12));
        prompt.setMultiLine(true,true);lyrics.setMultiLine(true,true);prompt.setReturnKeyStartsNewLine(true);lyrics.setReturnKeyStartsNewLine(true);prompt.setInputRestrictions(2000);lyrics.setInputRestrictions(4096);duration.setInputRestrictions(6,"0123456789.");seed.setInputRestrictions(10,"0123456789");
        for(auto* e:{&prompt,&lyrics,&duration,&seed}){e->setFont(design::labelFont(13));e->setColour(juce::TextEditor::backgroundColourId,design::paper);e->setColour(juce::TextEditor::textColourId,design::ink);e->setColour(juce::TextEditor::outlineColourId,design::rule);e->setColour(juce::TextEditor::focusedOutlineColourId,design::focus);}
        // TextEditor retains colour/font per inserted text section. Initialize
        // the value after the palette so the default is visible on paper.
        duration.setText("20",false);
        for(auto* label:{&title,&promptLabel,&lyricsLabel,&durationLabel,&seedLabel,&context,&status})label->setColour(juce::Label::textColourId,design::ink);
        for(auto* e:{&prompt,&lyrics,&duration,&seed})e->onTextChange=[this]{actionError.clear();};
        run.onClick=[this]{actionError.clear();start();};cancel.onClick=[this]{actionError.clear();if(jobId.isNotEmpty())request("cancel_generation_job",generationObject({{"job_id",jobId}}));};
        preview.onClick=[this]{actionError.clear();auto reply=request("preview_generation_result",generationObject({{"result_id",resultId}}));previewJobId=reply["job_id"].toString();previewing=previewJobId.isNotEmpty();previewState="preparing";poll();};
        stop.onClick=[this]{actionError.clear();stopPreview();poll();};
        add.onClick=[this]{actionError.clear();if(previewing)stopPreview();auto reply=request("accept_generation_result",generationObject({{"result_id",resultId},{"result_hash",result["result_hash"]}}));acceptId=reply["job_id"].toString();if(acceptId.isNotEmpty())add.setEnabled(false);};
        history.onChange=[this]{actionError.clear();if(previewing)stopPreview();const auto index=history.getSelectedId()-1;if(index>=0&&index<historyIds.size()){jobId=historyIds[index];result=juce::var();resultId={};acceptId={};lastState={};poll();}};
        language();poll();
    }
    juce::var request(const juce::String& command,const juce::var& args){
        const auto snapshot=session.snapshot();
        const auto reply=session.executeRequest(generationObject({{"request_id","generation-ui-"+juce::Uuid().toString()},
            {"project_id",snapshot.projectId},{"expected_revision",juce::int64(snapshot.revision)},{"command",command},{"args",args}}));
        const auto state=reply["status"].toString();
        if(state!="completed"&&state!="accepted"){
            auto error=reply["error"].toString();if(error.isEmpty())error=uiText("Generation request failed. Try again.","生成请求失败，请重试。");
            if(!command.startsWith("get_"))actionError=error;status.setText(error,juce::dontSendNotification);status.setTooltip(error);return {};
        }
        return reply["result"];
    }
    void start(){
        if(previewing)stopPreview();
        auto args=generationObject({{"prompt",prompt.getText()},{"lyrics",lyrics.getText()},{"duration_seconds",duration.getText().getDoubleValue()}});
        if(model.getSelectedId()>0)args.getDynamicObject()->setProperty("model_id",modelIds[model.getSelectedId()-1]);
        if(seed.getText().isNotEmpty())args.getDynamicObject()->setProperty("seed",juce::int64(seed.getText().getLargeIntValue()));
        auto reply=request("start_generation",args);const auto id=reply["job_id"].toString();if(id.isEmpty())return;
        jobId=id;resultId=reply["result_id"].toString();result=juce::var();acceptId={};lastState={};poll();
    }
    void stopPreview(){
        request("stop_generation_preview",generationObject({}));previewing=false;previewJobId.clear();previewState.clear();
    }
    void refreshCapabilities(){
        if(capabilityCountdown--<=0){
            const auto capabilities=request("get_generation_capabilities",generationObject({}));
            const auto previous=modelIds[model.getSelectedId()-1];providers.clear();modelIds.clear();model.clear(juce::dontSendNotification);
            int selected=0;if(const auto* values=capabilities["providers"].getArray())for(const auto& value:*values){
                providers.add(value);const auto id=value["model_id"].toString();modelIds.add(id);
                model.addItem(id=="yue2"?"YuE2":id=="ace-step-1.5-xl-turbo"?"ACE-Step 1.5 XL":id,modelIds.size());
                if(id==previous||previous.isEmpty()&&bool(value["default"]))selected=modelIds.size();
            }
            model.setSelectedId(selected>0?selected:modelIds.isEmpty()?0:1,juce::dontSendNotification);
            const int index=model.getSelectedId()-1;configured=index>=0&&index<providers.size()&&bool(providers[index]["available"]);capabilityCountdown=20;
        }
    }
    void pollPreview(){
        if(!previewing)return;
        if(previewJobId.isNotEmpty()){
            const auto preparation=request("get_job",generationObject({{"job_id",previewJobId}}));
            const auto phase=preparation["status"].toString();
            if(!preparation.isObject()||phase=="failed"||phase=="cancelled"){
                actionError=preparation.isObject()?preparation["error"].toString():status.getText();
                if(actionError.isEmpty())actionError=uiText("Preview was cancelled. Try Preview again.","试听已取消，请重新试听。");
                previewing=false;previewJobId.clear();previewState.clear();return;
            }
            if(phase!="completed"){previewState="preparing";return;}
            previewJobId.clear();
        }
        const auto playback=request("get_analysis_preview_status",generationObject({}));
        const auto phase=playback["status"].toString();
        if(!playback.isObject()||phase=="failed"||phase=="unavailable"){
            actionError=playback.isObject()?playback["detail"].toString():status.getText();
            if(actionError.isEmpty())actionError=uiText("Preview is unavailable. Check audio settings.","无法试听，请检查音频设置。");
            previewing=false;previewState.clear();
        }else if(phase=="completed"||phase=="stopped"){previewing=false;previewState.clear();}
        else previewState=phase=="playing"?"playing":"preparing";
    }
    void language(){
        title.setText(uiText("Generate music","生成音乐"),juce::dontSendNotification);
        promptLabel.setText(uiText("Describe the music","描述音乐"),juce::dontSendNotification);lyricsLabel.setText(uiText("Lyrics · optional","歌词 · 可选"),juce::dontSendNotification);
        durationLabel.setText(uiText("Seconds","秒数"),juce::dontSendNotification);seedLabel.setText(uiText("Seed","种子"),juce::dontSendNotification);
        prompt.setTextToShowWhenEmpty(uiText("Style, instruments and mood…","风格、乐器和情绪…"),design::secondary);lyrics.setTextToShowWhenEmpty(uiText("Leave empty for instrumental music","留空生成纯音乐"),design::secondary);seed.setTextToShowWhenEmpty(uiText("Random","随机"),design::secondary);
        run.setButtonText(uiText("Generate","生成"));cancel.setButtonText(uiText("Cancel","取消"));preview.setButtonText(uiText("Preview","试听"));stop.setButtonText(uiText("Stop","停止"));add.setButtonText(uiText("Add track","加入轨道"));history.setTextWhenNothingSelected(uiText("Recent generations","最近生成"));
        run.setTooltip(uiText("Uses the configured remote GPU. Creates a candidate without changing the project.","使用已配置的云端 GPU，先生成候选，不直接修改工程。"));
    }
    void poll(){
        const auto snapshot=session.snapshot();
        if(projectId!=snapshot.projectId){if(previewing)stopPreview();projectId=snapshot.projectId;jobId={};resultId={};acceptId={};result=juce::var();historyIds.clear();history.clear(juce::dontSendNotification);lastState={};actionError.clear();}
        refreshCapabilities();
        const auto jobs=request("get_generation_jobs",generationObject({}))["jobs"];
        juce::StringArray ids;if(jobs.isArray())for(const auto& j:*jobs.getArray())ids.add(j["job_id"].toString());
        if(ids!=historyIds){historyIds=ids;history.clear(juce::dontSendNotification);for(int i=0;i<ids.size();++i)history.addItem(uiText("Take ","候选 ")+juce::String(i+1),i+1);if(!ids.contains(jobId)&&!ids.isEmpty())jobId=ids[ids.size()-1];history.setSelectedId(ids.indexOf(jobId)+1,juce::dontSendNotification);}
        const bool locked=snapshot.recording||snapshot.recordingFinalizing||snapshot.nativePending;
        context.setText(juce::String(snapshot.bpm,1)+" BPM  ·  "+juce::String(snapshot.numerator)+"/"+juce::String(snapshot.denominator)+"  ·  "+uiText("at ","位置 ")+juce::String(snapshot.position,2)+" s",juce::dontSendNotification);
        juce::var task;if(jobId.isNotEmpty())task=request("get_generation_job",generationObject({{"job_id",jobId}}));
        const auto state=task["status"].toString();const bool busy=task.isObject()&&!finishedGeneration(state);
        if(task.isObject())resultId=task["result_id"].toString();
        if((state=="ready"||state=="applied")&&(!result.isObject()||lastState!=state||resultRevision!=snapshot.revision)){result=request("get_generation_result",generationObject({{"result_id",resultId}}));resultRevision=snapshot.revision;}
        lastState=state;
        const auto importTask=acceptId.isNotEmpty()?request("get_generation_job",generationObject({{"job_id",acceptId}})):juce::var();
        const bool importing=importTask.isObject()&&!finishedGeneration(importTask["status"].toString());
        if(importTask.isObject()&&finishedGeneration(importTask["status"].toString())){result=request("get_generation_result",generationObject({{"result_id",resultId}}));acceptId={};}
        const bool ready=result.isObject()&&!bool(result["stale"]);
        if(previewing&&(!ready||locked||snapshot.playing))stopPreview();
        pollPreview();
        run.setEnabled(configured&&!busy&&!importing&&!locked);cancel.setEnabled(busy);preview.setEnabled(ready&&!busy&&!importing&&!locked&&!snapshot.playing&&!previewing);stop.setEnabled(previewing);add.setEnabled(ready&&!bool(result["applied"])&&!importing&&!locked);
        history.setEnabled(!importing);model.setEnabled(!busy&&!importing);prompt.setEnabled(!busy);lyrics.setEnabled(!busy);duration.setEnabled(!busy);seed.setEnabled(!busy);
        if(importTask["error"].toString().isNotEmpty())actionError=importTask["error"].toString();
        if(actionError.isNotEmpty())status.setText(actionError,juce::dontSendNotification);
        else if(task["error"].toString().isNotEmpty())status.setText(task["error"].toString(),juce::dontSendNotification);
        else if(importing)status.setText(uiText("Adding local audio…","正在加入本地音频…"),juce::dontSendNotification);
        else if(result.isObject()&&bool(result["stale"]))status.setText(uiText("Project tempo or meter changed. Generate a new take.","工程速度或拍号已改变，请重新生成。"),juce::dontSendNotification);
        else if(previewing)status.setText(previewState=="playing"?uiText("Listening","试听中"):uiText("Preparing preview…","准备试听…"),juce::dontSendNotification);
        else if(result.isObject())status.setText(juce::String(double(result["audio"]["duration_seconds"]),1)+" s · "+(bool(result["applied"])?uiText("Added to arrangement","已加入编曲"):bool(result["truncated"])?uiText("Token limit reached · ending may be cut","已达长度预算 · 结尾可能截断"):uiText("Ready · preview, then add","已就绪 · 试听后加入")),juce::dontSendNotification);
        else if(busy)status.setText(uiText("Generating… ","生成中… ")+task["phase"].toString(),juce::dontSendNotification);
        else if(state=="cancelled")status.setText(bool(task["remote_cancel_confirmed"])?uiText("Cancelled locally and on the server","本地和云端任务均已取消"):task["remote_status"].toString()=="cancelling"?uiText("Stopped locally · server cancellation pending","本地已停止 · 云端取消待完成"):uiText("Stopped locally · server cancellation unconfirmed","本地已停止 · 尚未确认云端取消"),juce::dontSendNotification);
        else status.setText(configured?uiText("Audio is added only when you choose Add track.","选择“加入轨道”后才会修改工程。"):uiText("Remote generation is not configured.","尚未配置远程生成。"),juce::dontSendNotification);
        status.setTooltip(status.getText());owner.repaint();
    }
};
GenerationPanel::GenerationPanel(EngineSession& s):impl(std::make_unique<Impl>(*this,s)){setSize(760,284);startTimerHz(4);}
GenerationPanel::~GenerationPanel(){stopTimer();impl->request("stop_generation_preview",generationObject({}));}
void GenerationPanel::visibilityChanged(){if(!isVisible())impl->stopPreview();else{impl->capabilityCountdown=0;impl->poll();}}
void GenerationPanel::refreshLanguage(){impl->language();impl->poll();}
void GenerationPanel::timerCallback(){if(isShowing()&&!impl->session.isControlBusy())impl->poll();}
void GenerationPanel::resized(){
    auto& p=*impl;auto area=getLocalBounds().reduced(12,8);auto header=area.removeFromTop(30);p.title.setBounds(header.removeFromLeft(130));p.model.setBounds(header.removeFromLeft(juce::jmin(178,header.getWidth()/2)));header.removeFromLeft(6);header.removeFromRight(64);p.history.setBounds(header);
    auto actions=area.removeFromBottom(32);p.run.setBounds(actions.removeFromLeft(90));actions.removeFromLeft(6);p.cancel.setBounds(actions.removeFromLeft(70));p.add.setBounds(actions.removeFromRight(104));actions.removeFromRight(6);p.stop.setBounds(actions.removeFromRight(66));actions.removeFromRight(6);p.preview.setBounds(actions.removeFromRight(82));
    area.removeFromBottom(7);auto left=area.removeFromLeft(area.getWidth()*54/100);area.removeFromLeft(16);
    auto options=left.removeFromBottom(28);p.durationLabel.setBounds(options.removeFromLeft(62));p.duration.setBounds(options.removeFromLeft(62));options.removeFromLeft(12);p.seedLabel.setBounds(options.removeFromLeft(48));p.seed.setBounds(options.removeFromLeft(juce::jmin(105,options.getWidth())));
    left.removeFromBottom(5);p.promptLabel.setBounds(left.removeFromTop(22));const int box=juce::jmax(35,(left.getHeight()-27)/2);p.prompt.setBounds(left.removeFromTop(box));left.removeFromTop(4);p.lyricsLabel.setBounds(left.removeFromTop(22));p.lyrics.setBounds(left);
    p.context.setBounds(area.removeFromTop(26));p.status.setBounds(area.removeFromBottom(36));p.waveBounds=area.reduced(0,8);
}
void GenerationPanel::paint(juce::Graphics& graphics){
    auto& p=*impl;graphics.fillAll(design::paper);graphics.setColour(design::rule);graphics.drawHorizontalLine(0,0,float(getWidth()));graphics.fillRect(p.waveBounds.toFloat().withHeight(1));
    const auto peaks=p.result["waveform_peaks"];
    if(peaks.isArray()&&peaks.size()==128){const auto r=p.waveBounds.toFloat();graphics.setColour(design::focus);for(int i=0;i<128;++i){const float h=juce::jmax(1.0f,float(double(peaks[i]))*r.getHeight());graphics.fillRect(r.getX()+i*r.getWidth()/128.0f,r.getCentreY()-h*.5f,juce::jmax(1.0f,r.getWidth()/128.0f-1),h);}}
    else{graphics.setColour(design::secondary);graphics.setFont(design::labelFont(13));graphics.drawFittedText(uiText("Your generated audio appears here","生成后的音频显示在这里"),p.waveBounds,juce::Justification::centred,2);}
}
juce::Result GenerationPanel::runInteractionSmokeTest(const juce::File& directory){
    if(impl->duration.getText()!="20"||impl->duration.findColour(juce::TextEditor::textColourId)!=design::ink)return juce::Result::fail("Default generation duration is missing or has the wrong foreground.");
    // Inject only the missing job ID; the ordinary engine lookup must fail and
    // the real UI poll must keep its error visible rather than claim Ready.
    impl->previewing=true;impl->previewJobId="missing-preview-"+juce::Uuid().toString();impl->pollPreview();
    const auto previewError=impl->actionError;impl->poll();
    if(impl->previewing||previewError.isEmpty()||impl->status.getText()!=previewError||impl->stop.isEnabled())return juce::Result::fail("Asynchronous preview errors were hidden or retained active controls.");
    impl->actionError.clear();
    // UI-state fixtures are explicit; they do not claim generated music or
    // physical playback. The stale state must explain why import is disabled.
    const auto previousResult=impl->result;const auto previousJob=impl->jobId;
    impl->jobId.clear();impl->result=generationObject({{"stale",true},{"applied",false}});impl->poll();
    const bool staleExplained=!impl->add.isEnabled()&&!impl->preview.isEnabled()&&impl->status.getText()==uiText("Project tempo or meter changed. Generate a new take.","工程速度或拍号已改变，请重新生成。");
    impl->result=previousResult;impl->jobId=previousJob;impl->poll();
    if(!staleExplained)return juce::Result::fail("Stale generation was displayed as ready.");
    juce::var capabilities;const auto read=impl->session.execute("get_generation_capabilities",generationObject({}),impl->session.snapshot().revision,&capabilities);
    if(read.failed())return read;
    const bool available=bool(capabilities["available"]);impl->configured=!available;impl->capabilityCountdown=0;impl->poll();
    if(impl->configured!=available)return juce::Result::fail("Generation capability cache did not refresh.");
    directory.createDirectory();for(const auto size:{juce::Point<int>{760,284},juce::Point<int>{600,284}}){setSize(size.x,size.y);resized();
        for(auto* c:std::initializer_list<juce::Component*>{&impl->prompt,&impl->lyrics,&impl->duration,&impl->seed,&impl->run,&impl->cancel,&impl->preview,&impl->stop,&impl->add})if(c->getWidth()<20||c->getHeight()<20||!getLocalBounds().contains(c->getBounds()))return juce::Result::fail("Generation controls escaped the dock.");
        auto shot=createComponentSnapshot(getLocalBounds());juce::PNGImageFormat png;auto stream=directory.getChildFile("generation-"+juce::String(size.x)+".png").createOutputStream();if(!stream||!png.writeImageToStream(shot,*stream))return juce::Result::fail("Cannot capture generation UI.");
    }return juce::Result::ok();
}
}
