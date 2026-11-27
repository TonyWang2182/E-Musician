#pragma once
#include <juce_core/juce_core.h>

// Resolve optional helpers outside the real-time engine. Installation directories
// are read-only; mutable model data belongs to the current user or an explicit root.
namespace emusician::runtime_paths {
inline juce::File userData() {
    const auto local = juce::SystemStats::getEnvironmentVariable("LOCALAPPDATA", {});
    return (juce::File::isAbsolutePath(local) ? juce::File(local)
        : juce::File::getSpecialLocation(juce::File::userApplicationDataDirectory)).getChildFile("E-musician");
}
inline juce::File dataRoot(const char* variable, const char* directory) {
    const auto value = juce::SystemStats::getEnvironmentVariable(variable, {});
    return juce::File::isAbsolutePath(value) ? juce::File(value) : userData().getChildFile(directory);
}
inline juce::File script(const juce::String& relative) {
    const auto packaged = juce::File::getSpecialLocation(juce::File::currentExecutableFile)
        .getSiblingFile("runtime").getChildFile("scripts").getChildFile(relative);
    if (packaged.existsAsFile()) return packaged;
   #ifdef EMUSICIAN_SOURCE_DIR
    return juce::File(EMUSICIAN_SOURCE_DIR).getChildFile("scripts").getChildFile(relative);
   #else
    return packaged;
   #endif
}
inline juce::File python() {
    const auto configured = juce::SystemStats::getEnvironmentVariable("EMUSICIAN_PYTHON", {});
    if (configured.isNotEmpty())
        return juce::File::isAbsolutePath(configured) ? juce::File(configured) : juce::File();
    const auto packaged = juce::File::getSpecialLocation(juce::File::currentExecutableFile)
        .getSiblingFile("runtime").getChildFile("python").getChildFile("python.exe");
    if (packaged.existsAsFile()) return packaged;
    juce::StringArray directories;
    directories.addTokens(juce::SystemStats::getEnvironmentVariable("PATH", {}),
                         JUCE_WINDOWS ? ";" : ":", "\"");
    for (const auto& directory : directories) {
        const auto cleaned = directory.trim().unquoted();
        if (!juce::File::isAbsolutePath(cleaned)) continue;
        const auto executable = juce::File(cleaned).getChildFile(JUCE_WINDOWS ? "python.exe" : "python3");
        if (executable.existsAsFile()) return executable;
    }
   #ifdef EMUSICIAN_AGENT_PYTHON
    return juce::File(EMUSICIAN_AGENT_PYTHON);
   #else
    return {};
   #endif
}
}
