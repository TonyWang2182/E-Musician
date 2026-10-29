// Control-thread observation only. Native meters capture bounded peaks; no
// project mutation, graph rebuild, file IO or OS calls in the audio callback.
void EngineSession::Impl::updateTelemetry(Snapshot& snapshot)
{
    const auto now=juce::Time::getMillisecondCounterHiRes();
    if(now-memoryReadAt>=1000){
        memoryReadAt=now;
#if JUCE_WINDOWS
        using ReadMemory=BOOL(WINAPI*)(HANDLE,PPROCESS_MEMORY_COUNTERS,DWORD);
        auto read=reinterpret_cast<ReadMemory>(GetProcAddress(GetModuleHandleW(L"kernel32.dll"),"K32GetProcessMemoryInfo"));
        PROCESS_MEMORY_COUNTERS_EX counters{};counters.cb=sizeof(counters);
        if(read&&read(GetCurrentProcess(),reinterpret_cast<PPROCESS_MEMORY_COUNTERS>(&counters),sizeof(counters))){
            workingSetBytes=juce::int64(counters.WorkingSetSize);privateBytes=juce::int64(counters.PrivateUsage);
        }
#endif
    }
    if(now-metersReadAt>=50){
        metersReadAt=now;std::set<juce::String> liveTracks,liveInputs,enumeratedInputs;
        for(const auto& binding:bindings){
            liveTracks.insert(binding.id);auto& tap=trackMeters[binding.id];if(!tap)tap=std::make_unique<MeterTap>();
            auto* plugin=binding.track->getLevelMeterPlugin();tap->bind(plugin?&plugin->measurer:nullptr);tap->sample();
        }
        std::erase_if(trackMeters,[&](const auto& entry){return !liveTracks.contains(entry.first);});
        for(const auto& track:snapshot.tracks)if(track.inputDeviceId.isNotEmpty())liveInputs.insert(track.inputDeviceId);
        for(auto* device:engine.getDeviceManager().getWaveInputDevices())if(liveInputs.contains(device->getDeviceID())){
            enumeratedInputs.insert(device->getDeviceID());
            auto& tap=inputMeters[device->getDeviceID()];if(!tap)tap=std::make_unique<MeterTap>();
            tap->bind(&device->levelMeasurer);tap->sample();
        }
        std::erase_if(inputMeters,[&](const auto& entry){return !enumeratedInputs.contains(entry.first);});
        auto* context=edit->getTransport().getCurrentPlaybackContext();
        masterMeter.bind(context?&context->masterLevels:nullptr);masterMeter.sample();
    }
    snapshot.memoryWorkingSetBytes=workingSetBytes;snapshot.memoryPrivateBytes=privateBytes;
    snapshot.masterPeakLeftDb=masterMeter.left;snapshot.masterPeakRightDb=masterMeter.right;snapshot.masterOverloaded=masterMeter.overloaded;
    for(auto& track:snapshot.tracks){
        if(auto it=trackMeters.find(track.id);it!=trackMeters.end()){
            track.peakLeftDb=it->second->left;track.peakRightDb=it->second->right;track.overloaded=it->second->overloaded;
        }
        if(auto it=inputMeters.find(track.inputDeviceId);it!=inputMeters.end())track.inputPeakDb=std::max(it->second->left,it->second->right);
    }
}
void EngineSession::Impl::resetMeters()
{
    masterMeter.reset();for(auto& [id,tap]:trackMeters)tap->reset();for(auto& [id,tap]:inputMeters)tap->reset();
}
