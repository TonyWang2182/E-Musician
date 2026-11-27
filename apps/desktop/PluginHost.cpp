#include "PluginHost.h"
#include "ReplayMode.h"
#include "NativeInstrument.h"
#include "NativeEffects.h"
#include <juce_cryptography/juce_cryptography.h>
#include <algorithm>
#include <atomic>
#include <cmath>
#include <cstring>
#include <map>
#include <set>
#include <stdexcept>

namespace emusician::plugins {
namespace te = tracktion;
namespace {
constexpr int scanTimeoutMs = 30000;
constexpr int maximumCatalogEntries = 4096;
constexpr int maximumParameters = 65536;
constexpr juce::int64 maximumScanReplyBytes = 4 * 1024 * 1024;
constexpr size_t maximumStateBytes = 64 * 1024 * 1024;
constexpr char stateMagic[] = "EMUPLUG1";

void requireMessageThread()
{
    jassert(juce::MessageManager::getInstance()->isThisTheMessageThread());
}
bool supportedFormat(const juce::String& format) { return format == "VST" || format == "VST3"; }
bool isVst3BundleInterior(const juce::File& file)
{
    // A recursive VST2 search also sees support DLLs inside VST3 bundles.
    // Those DLLs (e.g. Steinberg's REX library) are not independently loadable
    // plugins. Keep the bundle as the only scan identity, including in caches.
    for (auto parent = file.getParentDirectory(); parent != parent.getParentDirectory(); parent = parent.getParentDirectory())
        if (parent.hasFileExtension("vst3")) return true;
    return false;
}
bool sameIdentity(const juce::PluginDescription& a, const juce::PluginDescription& b)
{
    return a.pluginFormatName == b.pluginFormatName && a.uniqueId == b.uniqueId
        && a.deprecatedUid == b.deprecatedUid
        && juce::File(a.fileOrIdentifier) == juce::File(b.fileOrIdentifier);
}
bool sameModuleReference(const juce::String& format, const juce::String& logical, const juce::String& runtime)
{
    if (!juce::File::isAbsolutePath(logical) || !juce::File::isAbsolutePath(runtime)) return false;
    const juce::File expected(logical), actual(runtime);
    if (expected == actual) return true;
   #if JUCE_WINDOWS && JUCE_64BIT
    // JUCE's Windows VST3 scanner can report the bundle, while the loaded
    // instance reports its binary. TE replaces desc with that runtime result
    // in prepareToPlay. Accept only this exact standard alias of the scanned
    // bundle, never another module, class, format or a same-name fallback.
    if (format == "VST3" && expected.hasFileExtension("vst3"))
        return actual == expected.getChildFile("Contents/x86_64-win").getChildFile(expected.getFileName());
   #endif
    return false;
}
juce::File cacheDirectory()
{
    if (showcase::enabled()) return showcase::profile().getChildFile("plugins-v1");
    return juce::File::getSpecialLocation(juce::File::userApplicationDataDirectory)
        .getChildFile("E-musician").getChildFile("plugins-v1");
}
juce::var object()
{
    return juce::var(new juce::DynamicObject());
}
juce::Result writeJson(const juce::File& file, const juce::var& value)
{
    if (auto r = file.getParentDirectory().createDirectory(); r.failed()) return r;
    juce::TemporaryFile temporary(file);
    auto stream = temporary.getFile().createOutputStream();
    if (!stream) return juce::Result::fail("Cannot create plugin data file.");
    if (!stream->writeText(juce::JSON::toString(value, true), false, false, "\n"))
        return juce::Result::fail("Cannot write plugin data file.");
    stream->flush();
    auto result = stream->getStatus();
    stream.reset();
    if (result.failed()) return result;
    return temporary.overwriteTargetFileWithTemporary() ? juce::Result::ok()
        : juce::Result::fail("Cannot replace plugin data file.");
}
bool readDescription(const juce::var& value, juce::PluginDescription& description)
{
    if (!value.isString() || value.toString().length() > 65536) return false;
    auto xml = juce::parseXML(value.toString());
    return xml && description.loadFromXml(*xml) && supportedFormat(description.pluginFormatName)
        && juce::File::isAbsolutePath(description.fileOrIdentifier);
}

class NativePluginWindow final : public juce::DocumentWindow {
public:
    explicit NativePluginWindow(te::Plugin& p)
        : DocumentWindow(p.getName(), juce::Colours::black, closeButton), plugin(p)
    {
        setUsingNativeTitleBar(true);
        setWantsKeyboardFocus(false);
        recreate();
        setBoundsConstrained(getLocalBounds() + p.windowState->choosePositionForPluginWindow());
        setVisible(true);
        toFront(true);
    }
    ~NativePluginWindow() override
    {
        setConstrainer(nullptr);
        clearContentComponent();
        editor.reset();
    }
    void recreate()
    {
        setConstrainer(nullptr);
        clearContentComponent();
        editor.reset();
        editor = plugin.createEditor();
        if (editor) {
            setContentNonOwned(editor.get(), true);
            setResizable(editor->allowWindowResizing(), false);
            if (editor->allowWindowResizing() && editor->getBoundsConstrainer())
                setConstrainer(editor->getBoundsConstrainer());
        }
    }
    bool hasEditor() const { return editor != nullptr; }
private:
    void closeButtonPressed() override { plugin.windowState->closeWindowExplicitly(); }
    void moved() override
    {
        if (plugin.windowState) plugin.windowState->lastWindowBounds = getBounds();
    }
    te::Plugin& plugin;
    std::unique_ptr<te::Plugin::EditorComponent> editor;
};

struct NativePluginUI final : te::UIBehaviour {
    std::unique_ptr<juce::Component> createPluginWindow(te::PluginWindowState& state) override
    {
        auto* window = dynamic_cast<te::Plugin::WindowState*>(&state);
        if (!window) return {};
        if (auto* external = dynamic_cast<te::ExternalPlugin*>(&window->plugin))
            if (!external->getAudioPluginInstance()) return {};
        auto result = std::make_unique<NativePluginWindow>(window->plugin);
        if (!result->hasEditor()) return {};
        return result;
    }
    void recreatePluginWindowContentAsync(te::Plugin& plugin) override
    {
        if (auto* window = dynamic_cast<NativePluginWindow*>(plugin.windowState->pluginWindow.get())) {
            juce::Component::SafePointer<NativePluginWindow> safe(window);
            juce::MessageManager::callAsync([safe] { if (safe) safe->recreate(); });
        } else te::UIBehaviour::recreatePluginWindowContentAsync(plugin);
    }
};

// Strict, bounded host envelope. Native plugin bytes are opaque. We do not parse
// arbitrary Tracktion ValueTrees or trust saved internal Edit item IDs.
struct CapturedState {
    int program = -1, inputChannels = 0, outputChannels = 2;
    juce::MemoryBlock native;
    std::vector<float> parameters;
};
struct ScopedProcessorSuspension {
    juce::AudioProcessor& processor;
    bool wasSuspended, enabled;
    explicit ScopedProcessorSuspension(juce::AudioProcessor& p,bool suspend=true) : processor(p), wasSuspended(p.isSuspended()), enabled(suspend)
    { if(enabled)processor.suspendProcessing(true); }
    ~ScopedProcessorSuspension() { if(enabled)processor.suspendProcessing(wasSuspended); }
};
juce::Result decodeState(const juce::MemoryBlock& bytes, CapturedState& out)
{
    if (bytes.getSize() == 0) return juce::Result::ok();
    if (bytes.getSize() < 28 || bytes.getSize() > maximumStateBytes)
        return juce::Result::fail("Plugin state size is invalid.");
    juce::MemoryInputStream input(bytes, false);
    char magic[8] {};
    if (input.read(magic, 8) != 8 || std::memcmp(magic, stateMagic, 8) != 0)
        return juce::Result::fail("Plugin state uses an unsupported host envelope.");
    CapturedState candidate;
    candidate.program = input.readInt();
    candidate.inputChannels = input.readInt();
    candidate.outputChannels = input.readInt();
    const int nativeSize = input.readInt();
    if (candidate.program < -1 || candidate.inputChannels < 0 || candidate.inputChannels > 2
        || candidate.outputChannels < 1 || candidate.outputChannels > 2 || nativeSize < 0
        || juce::int64(nativeSize) > input.getNumBytesRemaining() - 4)
        return juce::Result::fail("Plugin state layout or native size is invalid.");
    candidate.native.setSize(size_t(nativeSize));
    if (nativeSize > 0 && input.read(candidate.native.getData(), nativeSize) != nativeSize)
        return juce::Result::fail("Plugin native state is truncated.");
    const int count = input.readInt();
    if (count < 0 || count > maximumParameters || input.getNumBytesRemaining() != juce::int64(count) * 4)
        return juce::Result::fail("Plugin parameter fallback is invalid.");
    candidate.parameters.reserve(size_t(count));
    for (int i = 0; i < count; ++i) {
        const float value = input.readFloat();
        if (!std::isfinite(value) || value < 0 || value > 1)
            return juce::Result::fail("Plugin parameter fallback contains an invalid value.");
        candidate.parameters.push_back(value);
    }
    out = std::move(candidate);
    return juce::Result::ok();
}
juce::AudioProcessor::BusesLayout simpleLayout(juce::AudioProcessor& processor, int in, int out)
{
    auto layout = processor.getBusesLayout();
    for (int i = 0; i < layout.inputBuses.size(); ++i)
        layout.inputBuses.set(i, i == 0 ? juce::AudioChannelSet::canonicalChannelSet(in) : juce::AudioChannelSet::disabled());
    for (int i = 0; i < layout.outputBuses.size(); ++i)
        layout.outputBuses.set(i, i == 0 ? juce::AudioChannelSet::canonicalChannelSet(out) : juce::AudioChannelSet::disabled());
    return layout;
}
juce::String parameterId(juce::AudioProcessorParameter& parameter,int index)
{
    if(auto* named=dynamic_cast<juce::AudioProcessorParameterWithID*>(&parameter))return named->paramID;
    return juce::String(index);
}
juce::Result replayParameters(te::ExternalPlugin& plugin,const CapturedState& captured)
{
    auto* processor=plugin.getAudioPluginInstance();if(!processor)return juce::Result::fail("Cannot restore parameters of a missing plugin.");
    // Native-only EMUPLUG1 envelopes written by earlier builds remain valid.
    if(captured.parameters.empty()&&captured.native.getSize()>0)return juce::Result::ok();
    const auto& parameters=processor->getParameters();
    if(captured.parameters.size()!=size_t(parameters.size()))return juce::Result::fail("Plugin parameter layout changed since this snapshot was saved.");
    ScopedProcessorSuspension suspension(*processor);
    for(int i=0;i<parameters.size();++i){
        const auto value=captured.parameters[size_t(i)];auto* raw=parameters[i];
        // Do not resend unchanged program/mode parameters: a plugin may treat a
        // redundant selector update as an instruction to replace the preset.
        if(raw->getValue()!=value)raw->setValue(value);
        auto automatable=plugin.getAutomatableParameterByID(parameterId(*raw,i));
        if(automatable&&automatable!=plugin.dryGain&&automatable!=plugin.wetGain
            &&automatable->getCurrentNormalisedValue()!=value)
            automatable->setNormalisedParameter(value,juce::dontSendNotification);
    }
    return juce::Result::ok();
}
juce::MemoryBlock parameterCache(const CapturedState& captured)
{
    juce::MemoryOutputStream output;
    output.write(stateMagic,8);output.writeInt(-1);output.writeInt(captured.inputChannels);output.writeInt(captured.outputChannels);
    output.writeInt(0);output.writeInt(int(captured.parameters.size()));for(auto value:captured.parameters)output.writeFloat(value);
    return output.getMemoryBlock();
}
juce::MemoryBlock tracktionLayout(const juce::AudioProcessor::BusesLayout& buses)
{
    juce::ValueTree root(te::IDs::LAYOUT);
    auto append=[&](const auto& list,juce::Identifier kind){
        juce::ValueTree group(kind);
        for(int i=0;i<list.size();++i){
            const auto& channels=list.getReference(i);juce::ValueTree bus(te::IDs::BUS);
            bus.setProperty(te::IDs::index,i,nullptr);
            bus.setProperty(te::IDs::layout,channels.isDisabled()?"disabled":channels.getSpeakerArrangementAsString(),nullptr);
            group.addChild(bus,-1,nullptr);
        }
        root.addChild(group,-1,nullptr);
    };
    append(buses.inputBuses,te::IDs::INPUTS);append(buses.outputBuses,te::IDs::OUTPUTS);
    juce::MemoryOutputStream output;root.writeToStream(output);return output.getMemoryBlock();
}
juce::Result cacheCapturedState(te::ExternalPlugin& plugin,const storage::StoredPlugin& stored,juce::ValueTree slot)
{
    CapturedState captured;if(auto result=decodeState(stored.state,captured);result.failed())return result;
    auto* processor=plugin.getAudioPluginInstance();if(!processor)return juce::Result::fail("Cannot cache a missing plugin.");
    if(slot.isValid()&&slot["id"].toString()!=stored.id)return juce::Result::fail("Plugin cache slot identity mismatch.");
    // Assemble all bounded data first; no audio state or user edit changes here.
    const auto layout=tracktionLayout(processor->getBusesLayout());
    const auto native=captured.native.getSize()?captured.native.toBase64Encoding():juce::String();
    juce::MemoryOutputStream parameters;
    if(!captured.parameters.empty()){
        const auto& nativeParameters=processor->getParameters();
        if(captured.parameters.size()!=size_t(nativeParameters.size()))return juce::Result::fail("Plugin parameter layout changed before caching Undo state.");
        for(int i=0;i<nativeParameters.size();++i){
            const auto id=parameterId(*nativeParameters[i],i);
            auto parameter=plugin.getAutomatableParameterByID(id);
            if(!parameter||parameter==plugin.dryGain||parameter==plugin.wetGain)continue;
            parameters.writeString(id);parameters.writeFloat(captured.parameters[size_t(i)]);
        }
    }
    auto state=plugin.state;
    state.setProperty("emUndoFormat",stored.format,nullptr);
    state.setProperty("emUndoIdentifier",stored.identifier,nullptr);
    state.setProperty("emUndoUniqueId",stored.uniqueId,nullptr);
    state.setProperty("emUndoDeprecatedUid",stored.deprecatedUniqueId,nullptr);
    state.setProperty("emUndoVersion",stored.version,nullptr);
    state.setProperty("emUndoRole",stored.role,nullptr);
    state.setProperty(te::IDs::programNum,captured.program,nullptr);
    if(native.isNotEmpty()){
        state.setProperty(te::IDs::state,native,nullptr);
        state.removeProperty("emUndoFallback",nullptr);
    }else{
        state.removeProperty(te::IDs::state,nullptr);
        state.setProperty("emUndoFallback",juce::var(stored.state),nullptr);
    }
    // TE restores IDs::parameters after its native chunk and parameter-list
    // creation. This handles stopped VST3 edits whose component state lags the
    // host's queued parameter values. Keep raw non-automatable values separately
    // for first-watch replay, without duplicating the large native chunk.
    if(parameters.getDataSize())state.setProperty(te::IDs::parameters,juce::var(parameters.getMemoryBlock()),nullptr);
    else state.removeProperty(te::IDs::parameters,nullptr);
    if(!captured.parameters.empty())state.setProperty("emUndoParameters",juce::var(parameterCache(captured)),nullptr);
    else state.removeProperty("emUndoParameters",nullptr);
    if(auto legacy=state.getChildWithName(te::IDs::VSTDATA);legacy.isValid())state.removeChild(legacy,nullptr);
    state.setProperty(te::IDs::layout,juce::var(layout),nullptr);
    if(slot.isValid())slot.setProperty("data",juce::var(stored.state),nullptr);
    return juce::Result::ok();
}
}

std::unique_ptr<te::UIBehaviour> createUIBehaviour() { return std::make_unique<NativePluginUI>(); }

struct PluginHost::Impl final : private juce::Thread {
    struct Watcher final : juce::AudioProcessorListener {
        te::Plugin::Ptr plugin;
        juce::AudioProcessor* processor = nullptr;
        juce::String id;
        juce::ValueTree slot;
        std::atomic<bool> changed { false };
        std::atomic<std::uint64_t> generation { 0 };
        std::unique_ptr<std::atomic<float>[]> lastValues;
        // Immutable mappings are prepared on the message thread. Keeping the
        // parameter references alive makes callback reads safe across a native
        // parameter-list refresh; an invalidated layout is handled conservatively.
        std::vector<te::AutomatableParameter::Ptr> hostedParameters;
        std::vector<juce::AudioProcessorParameter*> nativeParameters;
        std::atomic<std::uint64_t> mappingInvalidations{0},mappingValidated{0};
        std::uint64_t mappingChecked=0;
        int parameterCount = 0;
        Watcher(const te::Plugin::Ptr& p, const juce::String& stableId) : plugin(p), id(stableId)
        {
            // Retain only the small logical slot tree, not its owning track.
            // Undo may detach that tree before this watcher is released.
            auto* track = plugin->getOwnerTrack();
            auto owner = track ? track->state : plugin->edit.state.getChildWithName("EM_PROJECT");
            slot = owner.getChildWithName("EM_PLUGINS").getChildWithProperty("id", id);
            processor = plugin->getWrappedAudioProcessor();
            if (processor) {
                parameterCount = processor->getParameters().size();
                lastValues = std::make_unique<std::atomic<float>[]>(size_t(parameterCount));
                auto* external=dynamic_cast<te::ExternalPlugin*>(plugin.get());
                for (int i = 0; i < parameterCount; ++i) {
                    auto* raw=processor->getParameters()[i];
                    lastValues[size_t(i)].store(raw->getValue(), std::memory_order_relaxed);
                    nativeParameters.push_back(raw);
                    auto host=external?external->getAutomatableParameterByID(parameterId(*raw,i)):te::AutomatableParameter::Ptr{};
                    if(external&&(host==external->dryGain||host==external->wetGain))host=nullptr;
                    hostedParameters.push_back(std::move(host));
                }
                processor->addListener(this);
            }
        }
        ~Watcher() override
        {
            // The retained Plugin keeps this processor alive; callers detach
            // before any forceFullReinitialise that would replace its instance.
            if (processor) processor->removeListener(this);
        }
        void markChanged() { generation.fetch_add(1, std::memory_order_relaxed); changed.store(true, std::memory_order_release); }
        void checkParameterMapping()
        {
            const auto version=mappingInvalidations.load(std::memory_order_acquire);
            if(version==mappingChecked)return;mappingChecked=version;
            auto* external=dynamic_cast<te::ExternalPlugin*>(plugin.get());
            bool same=processor&&external&&processor->getParameters().size()==parameterCount;
            for(int i=0;same&&i<parameterCount;++i){
                auto* raw=processor->getParameters()[i];
                same=raw==nativeParameters[size_t(i)]
                    &&external->getAutomatableParameterByID(parameterId(*raw,i))==hostedParameters[size_t(i)];
            }
            if(same)mappingValidated.store(version,std::memory_order_release);
            else markChanged(); // A real layout change must not be mistaken for playback.
        }
        void audioProcessorParameterChanged(juce::AudioProcessor*, int index, float value) override
        {
            // Several plugins resend their entire parameter list during state
            // reads. A same-value notification is not another musical edit.
            if (index >= 0 && index < parameterCount && std::isfinite(value)) {
                const auto previous=lastValues[size_t(index)].exchange(value,std::memory_order_relaxed);
                if(mappingInvalidations.load(std::memory_order_acquire)==mappingValidated.load(std::memory_order_acquire)){
                    if(auto* hosted=hostedParameters[size_t(index)].get()){
                        // TE sets its atomic current value before calling the
                        // native setValue. An echo of that value is host-origin,
                        // including automation, rather than another user edit.
                        if(hosted->getCurrentNormalisedValue()==value)return;
                        // Do not compare only with the last notification here:
                        // automation may have moved silently since that value.
                    }else if(previous==value)return;
                }
            }
            markChanged();
        }
        void audioProcessorChanged(juce::AudioProcessor*, const ChangeDetails& details) override
        {
            if(details.parameterInfoChanged)mappingInvalidations.fetch_add(1,std::memory_order_release);
            if (details.programChanged || details.nonParameterStateChanged)
                markChanged();
        }
    };
    te::Engine& engine;
    mutable juce::CriticalSection mutex;
    ScanSnapshot progress;
    std::vector<CatalogEntry> entries;
    juce::FileSearchPath paths;
    juce::Array<juce::File> explicitModules;
    std::vector<std::unique_ptr<Watcher>> watchers;

    explicit Impl(te::Engine& e) : Thread("Plugin scanner supervisor"), engine(e)
    {
        loadCache();
        progress.status = "Scan installed plugins.";
    }
    ~Impl() override
    {
        signalThreadShouldExit();
        notify();
        // The supervisor checks cancellation every 25 ms and kills only its worker.
        stopThread(5000);
        watchers.clear();
    }
    void loadCache()
    {
        const auto file = cacheDirectory().getChildFile("catalog.json");
        if (!file.existsAsFile() || file.getSize() > 16 * 1024 * 1024) return;
        const auto value = juce::JSON::parse(file);
        if (int(value.getProperty("schema", 0)) != 1) return;
        auto* array = value.getProperty("plugins", {}).getArray();
        if (!array || array->size() > maximumCatalogEntries) return;
        for (const auto& item : *array) {
            CatalogEntry entry;
            if (!readDescription(item.getProperty("description", {}), entry.description)) continue;
            if (isVst3BundleInterior(juce::File(entry.description.fileOrIdentifier))) continue;
            entry.id = PluginHost::catalogId(entry.description);
            entry.available = bool(item.getProperty("available", true)) && juce::File(entry.description.fileOrIdentifier).exists();
            entry.error = item.getProperty("error", {}).toString();
            if (!entry.available && entry.error.isEmpty()) entry.error = "Plugin module is missing. Rescan after reinstalling it.";
            entries.push_back(std::move(entry));
        }
    }
    void saveCache()
    {
        juce::Array<juce::var> array;
        {
            const juce::ScopedLock lock(mutex);
            for (const auto& entry : entries) {
                auto item = object();
                item.getDynamicObject()->setProperty("description", entry.description.createXml()->toString());
                item.getDynamicObject()->setProperty("available", entry.available);
                item.getDynamicObject()->setProperty("error", entry.error);
                array.add(std::move(item));
            }
        }
        auto value = object();
        value.getDynamicObject()->setProperty("schema", 1);
        value.getDynamicObject()->setProperty("plugins", array);
        auto result = writeJson(cacheDirectory().getChildFile("catalog.json"), value);
        if (result.failed()) {
            const juce::ScopedLock lock(mutex);
            progress.status += " Catalog cache could not be saved.";
        }
    }
    juce::Result start(const juce::FileSearchPath& search,const juce::Array<juce::File>& modules)
    {
        const juce::ScopedLock lock(mutex);
        if (progress.running || isThreadRunning()) return juce::Result::fail("A plugin scan is already running.");
        if (search.getNumPaths() == 0 && modules.isEmpty()) return juce::Result::fail("Add a plugin search directory or module first.");
        if (search.getNumPaths() > 96 || modules.size() > 64) return juce::Result::fail("Plugin search limits exceeded (64 explicit modules).");
        for (int i = 0; i < search.getNumPaths(); ++i)
            if (!juce::File::isAbsolutePath(search[i].getFullPathName())) return juce::Result::fail("Plugin search directories must be absolute paths.");
        for(const auto& module:modules){
            if(!juce::File::isAbsolutePath(module.getFullPathName())||!module.exists()
                ||!(module.hasFileExtension("vst3")||(module.hasFileExtension("dll")&&module.existsAsFile())))
                return juce::Result::fail("Explicit modules must be existing VST2 .dll files or VST3 files/bundles.");
            if (isVst3BundleInterior(module))
                return juce::Result::fail("Select the top-level VST3 bundle, not a support library or binary inside it.");
        }
        paths = search;
        explicitModules = modules;
        progress = {};
        progress.running = true;
        progress.status = "Finding plugin modules...";
        if (!startThread()) { progress.running = false; return juce::Result::fail("Cannot start the plugin scan supervisor."); }
        return juce::Result::ok();
    }
    void cancel() { signalThreadShouldExit(); notify(); }
    void run() override
    {
        struct Module { juce::String format, path; };
        std::vector<Module> modules;
        auto addModule=[&](const juce::String& format,const juce::String& path){
            if (isVst3BundleInterior(juce::File(path))) return;
            if(modules.size()<maximumCatalogEntries&&std::none_of(modules.begin(),modules.end(),[&](const auto& m){return m.format==format&&juce::File(m.path)==juce::File(path);}))
                modules.push_back({format,path});
        };
        for(const auto& file:explicitModules)addModule(file.hasFileExtension("dll")?"VST":"VST3",file.getFullPathName());
        juce::AudioPluginFormatManager formats;
        formats.addDefaultFormats();
        for (auto* format : formats.getFormats()) {
            if (!supportedFormat(format->getName()) || paths.getNumPaths()==0) continue;
            const auto found = format->searchPathsForPlugins(paths, true, false);
            for (const auto& module : found) {
                if (threadShouldExit()) break;
                if (modules.size() >= maximumCatalogEntries) break;
                addModule(format->getName(),module);
            }
        }
        {
            const juce::ScopedLock lock(mutex);
            progress.total = int(modules.size());
        }
        const auto jobs = cacheDirectory().getChildFile("scan-jobs");
        const auto directoryResult = jobs.createDirectory();
        if (directoryResult.failed()) {
            const juce::ScopedLock lock(mutex);
            progress.running = false; progress.status = "Cannot create the plugin scan workspace.";
            return;
        }
        for (const auto& module : modules) {
            if (threadShouldExit()) break;
            {
                const juce::ScopedLock lock(mutex);
                progress.currentModule = module.path;
                progress.status = "Scanning " + juce::File(module.path).getFileName();
            }
            const auto resultFile = jobs.getChildFile(juce::Uuid().toString() + ".json");
            juce::String error;
            std::vector<juce::PluginDescription> found;
            juce::ChildProcess process;
            const juce::StringArray args { juce::File::getSpecialLocation(juce::File::currentExecutableFile).getFullPathName(),
                "--plugin-scan-worker", module.format, module.path, resultFile.getFullPathName() };
            if (!process.start(args, 0)) error = "Cannot start isolated scanner. No in-process fallback was attempted.";
            else {
                const double started = juce::Time::getMillisecondCounterHiRes();
                while (process.isRunning() && !threadShouldExit()
                       && juce::Time::getMillisecondCounterHiRes() - started < scanTimeoutMs) wait(25);
                if (process.isRunning()) {
                    process.kill(); process.waitForProcessToFinish(2000);
                    error = threadShouldExit() ? "Scan cancelled." : "Plugin scan timed out after 30 seconds. Retry explicitly if needed.";
                } else if (process.getExitCode() != 0) error = "Plugin scanner failed or crashed (exit " + juce::String(process.getExitCode()) + ").";
                else if (!resultFile.existsAsFile() || resultFile.getSize() > maximumScanReplyBytes)
                    error = "Plugin scanner returned no valid bounded result.";
                else {
                    const auto result = juce::JSON::parse(resultFile);
                    if (result.getProperty("status", {}).toString() != "completed") error = result.getProperty("error", "Plugin scan failed.").toString();
                    else if (auto* types = result.getProperty("types", {}).getArray()) {
                        if (types->size() > 256) error = "Plugin module reports too many contained plugins.";
                        else for (const auto& value : *types) {
                            juce::PluginDescription description;
                            if (!readDescription(value, description) || description.pluginFormatName != module.format
                                || !sameModuleReference(module.format, module.path, description.fileOrIdentifier)) { error = "Plugin scanner returned an invalid identity."; break; }
                            // JUCE may identify a Windows VST3 by its exact
                            // standard bundle binary. Canonicalise only that
                            // alias; retain the scanned class IDs and format.
                            description.fileOrIdentifier = module.path;
                            found.push_back(std::move(description));
                        }
                    } else error = "Plugin scanner returned an invalid list.";
                    if (found.empty() && error.isEmpty()) error = "No compatible 64-bit plugin was found in this module.";
                }
            }
            resultFile.deleteFile(); // Only the random file created for this scan.
            if(threadShouldExit())break; // Retain the previous valid catalog entry for an interrupted module.
            {
                const juce::ScopedLock lock(mutex);
                std::erase_if(entries, [&](const auto& e) { return e.description.pluginFormatName == module.format
                    && juce::File(e.description.fileOrIdentifier) == juce::File(module.path); });
                if (error.isNotEmpty()) {
                    ++progress.failures;
                    juce::PluginDescription description;
                    description.name = juce::File(module.path).getFileNameWithoutExtension();
                    description.fileOrIdentifier = module.path; description.pluginFormatName = module.format;
                    entries.push_back({PluginHost::catalogId(description), description, false, error});
                } else for (auto& description : found) {
                    if (entries.size() >= maximumCatalogEntries) break;
                    entries.push_back({PluginHost::catalogId(description), description, true, {}});
                }
                ++progress.completed;
            }
        }
        {
            const juce::ScopedLock lock(mutex);
            for (auto& entry : entries)
                if (!juce::File(entry.description.fileOrIdentifier).exists()) {
                    entry.available = false; entry.error = "Plugin module is missing.";
                }
            progress.cancelled = threadShouldExit();
            progress.currentModule = {};
            progress.status = progress.cancelled ? "Plugin scan cancelled. Completed results were retained."
                : "Plugin scan complete: " + juce::String(progress.completed) + " modules, " + juce::String(progress.failures) + " failed.";
        }
        saveCache();
        const juce::ScopedLock lock(mutex);
        progress.running = false;
    }
};

PluginHost::PluginHost(te::Engine& engine) : impl(std::make_unique<Impl>(engine))
{
    engine.getPluginManager().createBuiltInType<native::Instrument>();
    engine.getPluginManager().createBuiltInType<native_effects::Effect>();
}
PluginHost::~PluginHost() = default;
juce::FileSearchPath PluginHost::defaultSearchPaths()
{
    juce::FileSearchPath result;
    const juce::StringArray paths { "C:\\Program Files\\Common Files\\VST3", "C:\\Program Files\\VstPlugins",
        "C:\\Program Files\\Steinberg\\VstPlugins", "C:\\Program Files\\Common Files\\VST2",
        juce::File::getSpecialLocation(juce::File::userHomeDirectory).getChildFile("AppData/Local/Programs/Common/VST3").getFullPathName() };
    for (const auto& path : paths) if (juce::File(path).isDirectory()) result.add(juce::File(path));
    return result;
}
juce::Result PluginHost::scanAsync(const juce::FileSearchPath& paths,const juce::Array<juce::File>& modules) { return impl->start(paths,modules); }
void PluginHost::cancelScan() { impl->cancel(); }
ScanSnapshot PluginHost::scanSnapshot() const { const juce::ScopedLock lock(impl->mutex); return impl->progress; }
std::vector<CatalogEntry> PluginHost::catalog() const { const juce::ScopedLock lock(impl->mutex); return impl->entries; }
bool PluginHost::getDescription(const juce::String& id, juce::PluginDescription& result) const
{
    const juce::ScopedLock lock(impl->mutex);
    for (const auto& entry : impl->entries)
        if (entry.id == id && entry.available) { result = entry.description; return true; }
    return false;
}
bool PluginHost::isScanWorker(const juce::StringArray& arguments) { return arguments.contains("--plugin-scan-worker"); }
int PluginHost::runScanWorker(const juce::StringArray& arguments)
{
    requireMessageThread();
    const int index = arguments.indexOf("--plugin-scan-worker");
    if (index < 0 || index + 3 >= arguments.size()) return 2;
    const auto formatName = arguments[index + 1], module = arguments[index + 2], outputPath = arguments[index + 3];
    if (!supportedFormat(formatName) || !juce::File::isAbsolutePath(module) || !juce::File::isAbsolutePath(outputPath)) return 2;
    juce::AudioPluginFormatManager formats;
    formats.addDefaultFormats();
    juce::AudioPluginFormat* selected = nullptr;
    for (auto* format : formats.getFormats()) if (format->getName() == formatName) selected = format;
    auto reply = object();
    juce::Array<juce::var> types;
    if (isVst3BundleInterior(juce::File(module))) {
        reply.getDynamicObject()->setProperty("status", "failed");
        reply.getDynamicObject()->setProperty("error", "Select the top-level VST3 bundle, not a support library or binary inside it.");
    } else if (!selected) {
        reply.getDynamicObject()->setProperty("status", "failed");
        reply.getDynamicObject()->setProperty("error", "This build does not include the requested plugin format.");
    } else {
        juce::OwnedArray<juce::PluginDescription> descriptions;
        selected->findAllTypesForFile(descriptions, module);
        if (descriptions.size() > 256) return 3;
        for (auto* description : descriptions) types.add(description->createXml()->toString());
        reply.getDynamicObject()->setProperty("status", "completed");
        reply.getDynamicObject()->setProperty("types", types);
        // Explicit diagnostic only: the ordinary catalog scan remains metadata
        // only. The supervisor owns this worker's deadline and process lifetime.
        // A hidden native peer checks editor/peer ownership without a visible
        // editor, hardware device, or the user's live Edit. JUCE/plugin code may
        // defer IPlugView::attached until visible: this does not prove native
        // attachment or GUI acceptance.
        if (arguments.contains("--probe-editor") && !descriptions.isEmpty()) {
            auto reportStage = [&](const juce::String& stage) {
                reply.getDynamicObject()->setProperty("probe_stage", stage);
                reply.getDynamicObject()->setProperty("status", "running");
                return writeJson(juce::File(outputPath), reply).wasOk();
            };
            try {
                if (!reportStage("instantiate")) return 4;
                juce::String error;
                auto processor = formats.createPluginInstance(*descriptions[0], 48000.0, 512, error);
                if (!processor) throw std::runtime_error(error.toStdString());
                if (!processor->setBusesLayout(simpleLayout(*processor, descriptions[0]->isInstrument ? 0 : 2, 2))
                    && !processor->setBusesLayout(simpleLayout(*processor, descriptions[0]->isInstrument ? 0 : 1, 1)))
                    throw std::runtime_error("Plugin does not support the host's mono/stereo layout.");
                processor->setRateAndBufferSizeDetails(48000.0, 512);
                processor->prepareToPlay(48000.0, 512);
                if (!reportStage("create_editor_no_peer")) return 4;
                std::unique_ptr<juce::AudioProcessorEditor> editor(processor->createEditorIfNeeded());
                reply.getDynamicObject()->setProperty("has_native_editor", editor != nullptr);
                if (editor) {
                    juce::MessageManager::getInstance()->runDispatchLoopUntil(200);
                    if (!reportStage("attach_hidden_peer")) return 4;
                    juce::Component hiddenHost;
                    hiddenHost.setBounds(0, 0, juce::jmax(1, editor->getWidth()), juce::jmax(1, editor->getHeight()));
                    hiddenHost.addToDesktop(juce::ComponentPeer::windowIsTemporary | juce::ComponentPeer::windowIgnoresKeyPresses);
                    hiddenHost.addAndMakeVisible(*editor);
                    juce::MessageManager::getInstance()->runDispatchLoopUntil(600);
                    if (!reportStage("detach_hidden_peer")) return 4;
                    hiddenHost.removeChildComponent(editor.get());
                    editor.reset();
                    hiddenHost.removeFromDesktop();
                    juce::MessageManager::getInstance()->runDispatchLoopUntil(100);
                }
                if (!reportStage("release_processor")) return 4;
                processor->releaseResources();
                processor.reset();
                reply.getDynamicObject()->setProperty("probe_stage", "completed");
                reply.getDynamicObject()->setProperty("status", "completed");
                reply.getDynamicObject()->setProperty("visible_editor_tested", false);
            } catch (const std::exception& e) {
                reply.getDynamicObject()->setProperty("status", "failed");
                reply.getDynamicObject()->setProperty("error", juce::String(e.what()));
            } catch (...) {
                reply.getDynamicObject()->setProperty("status", "failed");
                reply.getDynamicObject()->setProperty("error", "Plugin editor probe threw an exception.");
            }
        }
    }
    return writeJson(juce::File(outputPath), reply).wasOk() ? 0 : 4;
}
juce::String PluginHost::catalogId(const juce::PluginDescription& description)
{
    const auto text = description.pluginFormatName + "\n" + description.fileOrIdentifier.toLowerCase()
        + "\n" + juce::String(description.uniqueId) + "\n" + juce::String(description.deprecatedUid);
    return juce::SHA256(text.toRawUTF8(), size_t(text.getNumBytesAsUTF8())).toHexString();
}
storage::StoredPlugin PluginHost::describe(const juce::PluginDescription& description)
{
    storage::StoredPlugin result;
    result.id = juce::Uuid().toString(); result.format = description.pluginFormatName;
    result.identifier = description.fileOrIdentifier; result.uniqueId = description.uniqueId;
    result.deprecatedUniqueId = description.deprecatedUid;
    result.name = description.name; result.manufacturer = description.manufacturerName; result.version = description.version;
    result.role = description.isInstrument ? "instrument" : "effect";
    return result;
}
te::Plugin::Ptr PluginHost::instantiate(te::Edit& edit, const storage::StoredPlugin& stored, juce::Result& result)
{
    requireMessageThread();
    if (stored.format == "E-musician") {
        std::vector<juce::String> references;
        result = storage::nativePluginAssetIds(stored, references);
        if (result.failed()) return {};
        if (stored.role == "effect") {
            auto plugin=edit.getPluginCache().createNewPlugin(native_effects::Effect::xmlTypeName, {});
            if (!plugin || !dynamic_cast<native_effects::Effect*>(plugin.get())) { result=juce::Result::fail("Could not create native effect."); return {}; }
            if(stored.identifier=="native.delay")static_cast<native_effects::Effect*>(plugin.get())->prepareDelay();
            if(stored.identifier=="native.reverb")static_cast<native_effects::Effect*>(plugin.get())->prepareReverb();
            plugin->state.setProperty("emEffectType",stored.identifier,nullptr);
            plugin->state.setProperty("emEffectData",juce::var(stored.state),nullptr);
            plugin->state.setProperty("emId",stored.id,nullptr);plugin->setEnabled(stored.enabled);return plugin;
        }
        auto plugin = edit.getPluginCache().createNewPlugin(native::Instrument::xmlTypeName, {});
        if (!plugin || dynamic_cast<native::Instrument*>(plugin.get()) == nullptr) {
            result = juce::Result::fail("Could not create native instrument."); return {};
        }
        plugin->state.setProperty("emId", stored.id, nullptr);
        plugin->setEnabled(stored.enabled);
        return plugin;
    }
    CapturedState saved;
    result = decodeState(stored.state, saved);
    if (result.failed()) return {};
    juce::PluginDescription description;
    bool found = false;
    {
        const juce::ScopedLock lock(impl->mutex);
        for (const auto& entry : impl->entries)
            if (entry.available && entry.description.pluginFormatName == stored.format
                && entry.description.uniqueId == stored.uniqueId && entry.description.deprecatedUid == stored.deprecatedUniqueId
                && sameModuleReference(stored.format, entry.description.fileOrIdentifier, stored.identifier)) {
                description = entry.description; found = true; break;
            }
    }
    if (!found || !juce::File(description.fileOrIdentifier).exists()) {
        result = juce::Result::fail("Plugin is missing or has not passed a scan: " + stored.name); return {};
    }
    // EMUPLUG1 parameter values are positional. Native preset migration alone
    // cannot make those indices safe across a plugin version change.
    if (!saved.parameters.empty() && stored.version.isNotEmpty() && stored.version != description.version) {
        result = juce::Result::fail("Plugin version changed from " + stored.version + " to " + description.version
            + "; its positional parameter snapshot was preserved without loading: " + stored.name);
        return {};
    }
    if ((stored.role == "instrument") != description.isInstrument) {
        result = juce::Result::fail("Saved plugin role does not match the scanned plugin."); return {};
    }
    auto& manager = impl->engine.getPluginManager();
    manager.knownPluginList.addType(description);
    // Tracktion has legacy same-name fallback matching. Guard the actual factory
    // invocation so it can never instantiate another format/module/UID instead.
    const auto previousFactory = manager.createPluginInstance;
    struct FactoryRestorer {
        te::PluginManager& manager;
        decltype(manager.createPluginInstance) previous;
        ~FactoryRestorer() { manager.createPluginInstance = std::move(previous); }
    } restore { manager, previousFactory };
    manager.createPluginInstance = [&manager, description](const juce::PluginDescription& requested, double rate, int block, juce::String& error) {
        if (!sameIdentity(requested, description)) {
            error = "Exact plugin identity mismatch; same-name fallback was refused.";
            return std::unique_ptr<juce::AudioPluginInstance>();
        }
        return manager.pluginFormatManager.createPluginInstance(requested, rate, block, error);
    };
    auto plugin = edit.getPluginCache().createNewPlugin(te::ExternalPlugin::xmlTypeName, description);
    auto* external = dynamic_cast<te::ExternalPlugin*>(plugin.get());
    auto* processor = external ? external->getAudioPluginInstance() : nullptr;
    if (!external || !processor || external->getLoadError().isNotEmpty() || !sameIdentity(external->desc, description)) {
        const auto error = external ? external->getLoadError() : juce::String("Cannot create plugin instance.");
        result = juce::Result::fail(error.isNotEmpty() ? error : "Plugin instance identity mismatch.");
        return {};
    }
    const int in = stored.state.getSize() ? saved.inputChannels : (description.isInstrument ? 0 : 2);
    const int out = stored.state.getSize() ? saved.outputChannels : 2;
    bool layoutOk = external->setBusesLayout(simpleLayout(*processor, in, out));
    if (!layoutOk && stored.state.getSize() == 0)
        layoutOk = external->setBusesLayout(simpleLayout(*processor, description.isInstrument ? 0 : 1, 1));
    if (!layoutOk) { result = juce::Result::fail("Plugin does not support the saved mono/stereo bus layout."); return {}; }
    if (stored.state.getSize() > 0) {
        ScopedProcessorSuspension suspension(*processor);
        // JUCE VST3 queues program selection for the next process block. Even a
        // call before setStateInformation could overwrite its restored native
        // preset later, so native VST3 state is the sole program authority.
        const bool nativeVst3 = stored.format == "VST3" && saved.native.getSize() > 0;
        if (!nativeVst3 && saved.program >= 0 && saved.program < processor->getNumPrograms()
            && saved.program != processor->getCurrentProgram()) processor->setCurrentProgram(saved.program);
        if (saved.native.getSize() > 0) processor->setStateInformation(saved.native.getData(), int(saved.native.getSize()));
        // Reapply only after the native chunk. Setting a program here would
        // replace the just-restored preset, so program selection remains above.
        if(auto restored=replayParameters(*external,saved);restored.failed()){result=restored;return {};}
        if (!external->setBusesLayout(simpleLayout(*processor, saved.inputChannels, saved.outputChannels))) {
            result = juce::Result::fail("Plugin state changed its buses to an unsupported layout."); return {};
        }
    }
    external->setEnabled(stored.enabled);
    plugin->state.setProperty("emId", stored.id, nullptr);
    // Cache once at this structural boundary. No instance retention is needed
    // for an Undo after the one-second Tracktion plugin-cache cleanup.
    if(stored.state.getSize()){
        // Older playing saves may contain the exact runtime binary alias.
        // The lookup above resolved it to this scanned module/class/version;
        // retain that canonical identity for subsequent capture and Undo.
        auto canonical=stored;canonical.identifier=description.fileOrIdentifier;
        result=cacheCapturedState(*external,canonical,{});
    }
    else result=cacheStateForUndo(*external);
    if(result.failed())return {};
    result = juce::Result::ok();
    return plugin;
}
juce::Result PluginHost::capture(te::Plugin& plugin, storage::StoredPlugin& output, bool flushState)
{
    requireMessageThread();
    auto* external = dynamic_cast<te::ExternalPlugin*>(&plugin);
    if (!external || !external->getAudioPluginInstance()) return juce::Result::fail("Cannot capture a missing plugin; keep its existing state.");
    if (!matchesCachedIdentity(*external)) return juce::Result::fail("Loaded plugin identity or version differs from its cached slot.");
    const auto logicalIdentifier = external->state.getProperty("emUndoIdentifier", external->state[te::IDs::filename]).toString();
    if (!sameModuleReference(external->desc.pluginFormatName, logicalIdentifier, external->desc.fileOrIdentifier))
        return juce::Result::fail("Loaded plugin module does not match its original scanned identity.");
    auto updated = describe(external->desc);
    // Persist the identity which passed the exact catalog/factory checks.
    // A runtime bundle-to-binary spelling change is not a musical edit and
    // must not change the content key or make the saved plugin unresolvable.
    updated.identifier = logicalIdentifier;
    updated.id = output.id.isNotEmpty() ? output.id : plugin.state.getProperty("emId").toString();
    if (updated.id.isEmpty()) updated.id = juce::Uuid().toString();
    updated.enabled = external->isEnabled();
    if (!flushState) { updated.state = output.state; output = std::move(updated); return juce::Result::ok(); }
    auto* processor = external->getAudioPluginInstance();
    CapturedState captured;
    std::map<juce::String,float> explicitAutomationValues;
    auto* ownerTrack=external->getOwnerTrack();
    auto owner=ownerTrack?ownerTrack->state:external->edit.state.getChildWithName("EM_PROJECT");
    for(auto lane:owner.getChildWithName("EM_PRODUCTION"))
        if(lane.hasType("LANE")&&lane["target"].toString()=="plugin_parameter"&&lane["pluginId"].toString()==updated.id){
            const auto id=lane["parameterId"].toString();auto parameter=external->getAutomatableParameterByID(id);
            if(parameter&&parameter->hasAutomationPoints())
                explicitAutomationValues[id]=parameter->valueRange.convertTo0to1(parameter->getCurrentExplicitValue());
        }
    captured.inputChannels = processor->getMainBusNumInputChannels();
    captured.outputChannels = processor->getMainBusNumOutputChannels();
    if (captured.inputChannels > 2 || captured.outputChannels < 1 || captured.outputChannels > 2)
        return juce::Result::fail("Only mono/stereo plugin buses are supported.");
    {
        // VST3 permits UI-thread getState while processing. Suspending this
        // read would deliberately silence process blocks during every Save.
        // VST2 reads remain conservative; restore/write paths still suspend.
        ScopedProcessorSuspension suspension(*processor,updated.format!="VST3");
        captured.program = processor->getNumPrograms() > 0 ? processor->getCurrentProgram() : -1;
        processor->getStateInformation(captured.native);
        // VST3 may update its controller/cache while stopped without processing
        // the queued change in IComponent. Its native chunk alone can therefore
        // contain an older parameter value even though getValue is current.
        const auto& parameters = processor->getParameters();
        if (parameters.size() > maximumParameters) return juce::Result::fail("Plugin has too many snapshot parameters.");
        if(captured.native.getSize()>maximumStateBytes-28-size_t(parameters.size())*sizeof(float))return juce::Result::fail("Plugin state and parameter snapshot exceed 64 MiB.");
        captured.parameters.reserve(size_t(parameters.size()));
        for (int index=0;index<parameters.size();++index) {
            auto* parameter=parameters[index];float value=parameter->getValue();
            // Native chunks may contain the instantaneous automated value. The
            // replay envelope separately restores the user's explicit base for
            // our managed curves, without writing anything into the live plugin.
            // Unautomated parameters keep the raw value so a pending GUI change
            // cannot be replaced by TE's asynchronously updated parameter cache.
            if(auto found=explicitAutomationValues.find(parameterId(*parameter,index));found!=explicitAutomationValues.end())value=found->second;
            if (!std::isfinite(value)) return juce::Result::fail("Plugin returned a non-finite parameter.");
            captured.parameters.push_back(juce::jlimit(0.0f, 1.0f, value));
        }
    }
    juce::MemoryOutputStream stream;
    stream.write(stateMagic, 8); stream.writeInt(captured.program);
    stream.writeInt(captured.inputChannels); stream.writeInt(captured.outputChannels);
    stream.writeInt(int(captured.native.getSize())); stream.write(captured.native.getData(), captured.native.getSize());
    stream.writeInt(int(captured.parameters.size()));
    for (float value : captured.parameters) stream.writeFloat(value);
    updated.state = stream.getMemoryBlock();
    output = std::move(updated);
    return juce::Result::ok();
}
juce::Result PluginHost::cacheStateForUndo(te::Plugin& plugin,juce::ValueTree slot)
{
    requireMessageThread();auto* external=dynamic_cast<te::ExternalPlugin*>(&plugin);
    if(!external)return juce::Result::fail("Only external plugins have native Undo state.");
    storage::StoredPlugin captured;captured.id=plugin.state["emId"].toString();
    if(auto result=capture(plugin,captured,true);result.failed())return result;
    return cacheCapturedState(*external,captured,slot);
}
bool PluginHost::matchesCachedIdentity(const te::ExternalPlugin& plugin)
{
    const auto& state=plugin.state;if(!state.hasProperty("emUndoFormat"))return true;
    const auto version=state["emUndoVersion"].toString();
    return state["emUndoFormat"].toString()==plugin.desc.pluginFormatName
        && sameModuleReference(plugin.desc.pluginFormatName,state["emUndoIdentifier"].toString(),plugin.desc.fileOrIdentifier)
        && int(state["emUndoUniqueId"])==plugin.desc.uniqueId
        && int(state["emUndoDeprecatedUid"])==plugin.desc.deprecatedUid
        && (!state.hasProperty("emUndoRole") || state["emUndoRole"].toString()==(plugin.desc.isInstrument?"instrument":"effect"))
        && (!state.hasProperty("emUndoParameters") || version.isEmpty() || version==plugin.desc.version);
}
juce::Result PluginHost::restoreCachedProgramIfNeeded(te::ExternalPlugin& plugin)
{
    requireMessageThread();
    if(plugin.desc.pluginFormatName=="VST3" && plugin.state[te::IDs::state].toString().isNotEmpty()){
        if(!matchesCachedIdentity(plugin))return juce::Result::fail("Cached plugin identity or version does not match the loaded module.");
        auto* processor=plugin.getAudioPluginInstance();
        if(!processor)return juce::Result::fail("Plugin instance is missing during Undo restore.");
        // TE next calls setCurrentProgram only if this property differs from
        // the instance's current program, then restores the native chunk. Make
        // that comparison a no-op rather than queueing a later VST3 program
        // event. The opaque chunk, followed by raw parameter replay, restores
        // the saved program; no program selection follows the native restore.
        plugin.state.setProperty(te::IDs::programNum,processor->getCurrentProgram(),nullptr);
    }
    const auto* bytes=plugin.state["emUndoFallback"].getBinaryData();
    if(!bytes)return juce::Result::ok();
    if(!matchesCachedIdentity(plugin))return juce::Result::fail("Cached plugin identity does not match the loaded module.");
    CapturedState captured;if(auto result=decodeState(*bytes,captured);result.failed())return result;
    auto* processor=plugin.getAudioPluginInstance();if(!processor)return juce::Result::fail("Plugin instance is missing during Undo restore.");
    const auto& parameters=processor->getParameters();
    if(captured.native.getSize()!=0||captured.parameters.size()!=size_t(parameters.size()))return juce::Result::fail("Cached plugin fallback parameter layout changed.");
    ScopedProcessorSuspension suspension(*processor);
    if(captured.program>=0){if(captured.program>=processor->getNumPrograms())return juce::Result::fail("Cached plugin program no longer exists.");processor->setCurrentProgram(captured.program);}
    for(int i=0;i<parameters.size();++i)parameters[i]->setValue(captured.parameters[size_t(i)]);
    return juce::Result::ok();
}
juce::Result PluginHost::showEditor(te::Plugin& plugin)
{
    requireMessageThread();
    auto* external = dynamic_cast<te::ExternalPlugin*>(&plugin);
    if (!external || !external->getAudioPluginInstance()) return juce::Result::fail("This plugin is not loaded.");
    plugin.windowState->showWindowExplicitly();
    if (!plugin.windowState->isWindowShowing())
        return juce::Result::fail("The plugin editor could not open. Close any modal dialog and try again; the plugin may not provide an editor.");
    return juce::Result::ok();
}
void PluginHost::closeEditor(te::Plugin& plugin) { requireMessageThread(); plugin.windowState->closeWindowExplicitly(); }
void PluginHost::closeAllEditors(te::Edit& edit)
{
    requireMessageThread();
    for (auto* window : te::PluginWindowState::getAllWindows(edit)) window->closeWindowExplicitly();
}
void PluginHost::watchPlugin(const te::Plugin::Ptr& plugin, const juce::String& id)
{
    requireMessageThread();
    if (!plugin || id.isEmpty()) return;
    for (const auto& watcher : impl->watchers)
        if (watcher->id == id && watcher->plugin == plugin) return;
    // This path runs only on the first attachment of a new/recreated instance;
    // ordinary edits keep the existing watch and never replay stale snapshots.
    if(auto* external=dynamic_cast<te::ExternalPlugin*>(plugin.get());external&&external->getAudioPluginInstance()){
        if(const auto* bytes=plugin->state["emUndoParameters"].getBinaryData()){
            CapturedState parameters;auto result=decodeState(*bytes,parameters);
            if(result.wasOk())result=replayParameters(*external,parameters);
            if(result.failed())throw std::runtime_error(result.getErrorMessage().toStdString());
        }
    }
    unwatchPlugin(id);
    impl->watchers.push_back(std::make_unique<Impl::Watcher>(plugin, id));
}
juce::Result PluginHost::cacheDetachedPluginsForUndo(te::Edit& edit)
{
    requireMessageThread();
    // Enumerating bounded plugin chains does not walk clip/note trees or copy
    // opaque state for any instance that remains attached after ordinary Undo.
    std::set<const te::Plugin*> attached;
    for(auto* plugin:edit.getMasterPluginList())attached.insert(plugin);
    for(auto* track:te::getAudioTracks(edit))for(auto* plugin:track->pluginList)attached.insert(plugin);
    try {
        for(const auto& watcher:impl->watchers){
            if(&watcher->plugin->edit!=&edit || attached.contains(watcher->plugin.get()))continue;
            auto* external=dynamic_cast<te::ExternalPlugin*>(watcher->plugin.get());
            // A missing placeholder has no newer live state to capture.
            if(!external || !external->getAudioPluginInstance())continue;
            if(auto result=cacheStateForUndo(*external,watcher->slot);result.failed())return result;
        }
    }catch(const std::exception& error){return juce::Result::fail(error.what());}
    catch(...){return juce::Result::fail("Plugin failed while preserving structural Undo state.");}
    return juce::Result::ok();
}
void PluginHost::unwatchPlugin(const juce::String& id)
{
    requireMessageThread();
    std::erase_if(impl->watchers, [&](const auto& watcher) { return watcher->id == id; });
}
void PluginHost::detachEdit(te::Edit& edit)
{
    requireMessageThread();
    std::erase_if(impl->watchers, [&](const auto& watcher) { return &watcher->plugin->edit == &edit; });
}
std::vector<juce::String> PluginHost::takeChangedPluginIds()
{
    requireMessageThread();
    std::vector<juce::String> changed;
    for (const auto& watcher : impl->watchers)
    {
        watcher->checkParameterMapping();
        if (watcher->changed.exchange(false, std::memory_order_relaxed)) changed.push_back(watcher->id);
    }
    return changed;
}
std::uint64_t PluginHost::changeGeneration(const juce::String& id) const
{
    requireMessageThread();
    for (const auto& watcher : impl->watchers)
        if (watcher->id == id) return watcher->generation.load(std::memory_order_acquire);
    return 0;
}
bool PluginHost::hasPendingChanges() const
{
    requireMessageThread();
    return std::any_of(impl->watchers.begin(),impl->watchers.end(),[](const auto& watcher){
        return watcher->changed.load(std::memory_order_acquire);
    });
}
}
