// Included inside namespace emusician; integration checks have access to the private engine boundary.
juce::Result EngineSession::runOfflineSmokeTest(const juce::File& directory)
{
    requireControlThread();
    const auto dirResult = directory.createDirectory();
    if (dirResult.failed()) return dirResult;
    const auto input = directory.getChildFile("generated-tone.wav");
    // Owned deterministic test fixture: stereo sine with different channel pitches.
    juce::AudioBuffer<float> buffer(2, 96000);
    for (int ch = 0; ch < 2; ++ch)
        for (int i = 0; i < buffer.getNumSamples(); ++i)
            buffer.setSample(ch, i, 0.2f * float(std::sin(juce::MathConstants<double>::twoPi * (220.0 + ch * 110.0) * i / 48000.0)));
    juce::WavAudioFormat format;
    input.deleteFile();
    auto stream = input.createOutputStream();
    if (!stream) return juce::Result::fail("Fixture stream failed");
    std::unique_ptr<juce::AudioFormatWriter> writer(format.createWriterFor(stream.get(), 48000, 2, 24, {}, 0));
    if (!writer) return juce::Result::fail("Fixture writer failed");
    stream.release();
    if (!writer->writeFromAudioSampleBuffer(buffer, 0, buffer.getNumSamples()))
        return juce::Result::fail("Fixture write failed");
    writer.reset();
    auto result = importFile(input, snapshot().revision);
    if (result.failed()) return result;
    const auto imported = snapshot();
    if (std::abs(imported.duration - 2.0) > 1.0 / 48000 || imported.channels != 2)
        return juce::Result::fail("Imported duration/channels differ");
    if (importFile(input, imported.revision - 1).wasOk() || snapshot().revision != imported.revision)
        return juce::Result::fail("Stale import was not rejected");
    if (importFile(directory.getChildFile("missing.wav"), imported.revision).wasOk() || snapshot().source != input)
        return juce::Result::fail("Invalid import replaced source");
    seek(999.0);
    if (std::abs(snapshot().position - 2.0) > 0.001) return juce::Result::fail("Seek clamp failed");
    stop();
    if (snapshot().position != 0.0) return juce::Result::fail("Stop did not reset position");
    setLoop(true);
    if (!snapshot().looping) return juce::Result::fail("Loop state failed");
    setLoop(false);

    auto renderAndRead = [&](const juce::String& name, float gain, double& rms) -> juce::Result {
        setGain(gain);
        const auto output = directory.getChildFile(name);
        output.deleteFile();
        te::Renderer::Parameters params(*impl->edit);
        params.destFile = output;
        params.audioFormat = &format;
        params.sampleRateForAudio = 48000;
        params.blockSizeForAudio = 256;
        params.bitDepth = 24;
        params.canRenderInMono = false;
        params.useMasterPlugins = true;
        params.time = { te::TimePosition::fromSeconds(0), te::TimePosition::fromSeconds(2) };
        params.tracksToDo = te::toBitSet(te::getAllTracks(*impl->edit));
        {
            te::Edit::ScopedRenderStatus rendering(*impl->edit, true);
            te::Renderer::RenderTask task("Offline engine verification", params, nullptr, nullptr);
            while (task.runJob() == juce::ThreadPoolJob::jobNeedsRunningAgain) {}
            if (task.errorMessage.isNotEmpty()) return juce::Result::fail(task.errorMessage);
        }
        auto renderedStream = output.createInputStream();
        if (!renderedStream) return juce::Result::fail("Rendered output file is missing");
        std::unique_ptr<juce::AudioFormatReader> reader(format.createReaderFor(renderedStream.release(), true));
        if (!reader || reader->numChannels != 2 || reader->sampleRate != 48000 || std::abs(reader->lengthInSamples - 96000) > 1)
            return juce::Result::fail("Render format or duration mismatch");
        juce::AudioBuffer<float> rendered(2, int(reader->lengthInSamples));
        if (!reader->read(&rendered, 0, rendered.getNumSamples(), 0, true, true))
            return juce::Result::fail("Could not decode rendered audio");
        rms = rendered.getRMSLevel(0, 12000, 72000);
        if (!std::isfinite(rms) || rms < 0.01 || rms > 0.3)
            return juce::Result::fail("Rendered audio is silent or invalid");
        return juce::Result::ok();
    };
    double rmsA = 0.0, rmsB = 0.0;
    result = renderAndRead("render-minus6.wav", -6.0f, rmsA);
    if (result.failed()) return result;
    result = renderAndRead("render-minus12.wav", -12.0f, rmsB);
    if (result.failed()) return result;
    if (std::abs(rmsB / rmsA - std::pow(10.0, -6.0 / 20.0)) > 0.02)
        return juce::Result::fail("Master gain did not affect render correctly");
    setGain(-6.0f);
    impl->status = "Generated test tone loaded. Ready to audition.";
    const auto state = snapshot();
    auto report = std::make_unique<juce::DynamicObject>();
    report->setProperty("status", "passed");
    report->setProperty("scope", "offline render and control integration; no physical listening or realtime performance claim");
    report->setProperty("sample_rate", 48000);
    report->setProperty("samples", 96000);
    report->setProperty("channels", 2);
    report->setProperty("rms_minus6", rmsA);
    report->setProperty("rms_minus12", rmsB);
    report->setProperty("device_available", state.deviceAvailable);
    report->setProperty("device_name", state.deviceName);
    report->setProperty("device_sample_rate", state.sampleRate);
    report->setProperty("device_buffer_size", state.bufferSize);
    if (!directory.getChildFile("engine-report.json").replaceWithText(juce::JSON::toString(juce::var(report.release()))))
        return juce::Result::fail("Could not save engine test report");
    return juce::Result::ok();
}
