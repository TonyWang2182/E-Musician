#pragma once
#include <juce_core/juce_core.h>

// Compile-time isolated presentation package. Never enable this from a project
// document or a model response. Production builds cannot enter this path.
namespace emusician::showcase {
inline constexpr bool enabled() {
#if defined(EMUSICIAN_SHOWCASE) && EMUSICIAN_SHOWCASE
    return true;
#else
    return false;
#endif
}
inline juce::File root() {
#if defined(EMUSICIAN_SHOWCASE_ROOT)
    return juce::File(EMUSICIAN_SHOWCASE_ROOT);
#else
    return juce::File::getSpecialLocation(juce::File::currentExecutableFile).getSiblingFile("workspace");
#endif
}
inline juce::File profile() { return root().getChildFile("runtime"); }
inline juce::var manifest() {
    const auto file=root().getChildFile("manifest.json");
    if(!enabled()||!file.existsAsFile()||file.isSymbolicLink()||file.getSize()>256*1024)return {};
    const auto value=juce::JSON::parse(file);
    return value.isObject()&&int(value["schema_version"])==1?value:juce::var();
}
inline juce::var projects() { return manifest()["projects"]; }
inline juce::File projectFile(const juce::var& project) {
    const auto path=project["path"].toString();
    if(path.isEmpty()||juce::File::isAbsolutePath(path)||path.contains(".."))return {};
    const auto file=root().getChildFile(path);
    return file.isAChildOf(root())&&!file.isSymbolicLink()?file:juce::File();
}
inline juce::Array<juce::var> providers(const juce::String& kind={}) {
    juce::Array<juce::var> values;
    juce::StringArray identities;
    const auto scenarios=manifest()["scenarios"];
    if(const auto* list=scenarios.getArray())for(const auto& scene:*list){
        const auto task=scene["kind"].toString(), model=scene["model_id"].toString();
        if((kind.isNotEmpty()&&task!=kind)||model.isEmpty()||identities.contains(task+":"+model))continue;
        identities.add(task+":"+model);
        auto p=new juce::DynamicObject();
        p->setProperty("kind",task);p->setProperty("model_id",model);
        p->setProperty("available",true);p->setProperty("default",true);
        // The existing route vocabulary describes the model's original backend.
        // Worker dispatch is separately compile-time gated to local replay.
        p->setProperty("execution",task=="beats"?"local":"cloud");
        p->setProperty("max_duration_seconds",task=="generate"?120:600);
        p->setProperty("version","retained-result");p->setProperty("detail","Ready");
        if(task=="separate")p->setProperty("stems",juce::var(juce::Array<juce::var>{4}));
        values.add(juce::var(p));
    }
    return values;
}
inline juce::var registry() {
    auto r=new juce::DynamicObject();
    r->setProperty("schema_version",1);r->setProperty("available",manifest().isObject());
   #ifdef EMUSICIAN_AGENT_PYTHON
    r->setProperty("python_executable",EMUSICIAN_AGENT_PYTHON);
   #else
    r->setProperty("python_executable",juce::String());
   #endif
    r->setProperty("providers",juce::var(providers()));
    auto defaults=new juce::DynamicObject();
    for(const auto& provider:providers())defaults->setProperty(juce::Identifier(provider["kind"].toString()),provider["model_id"]);
    r->setProperty("defaults",juce::var(defaults));
    return juce::var(r);
}
}
