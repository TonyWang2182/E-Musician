#include "AudioWarp.h"
#include <signalsmith-stretch/signalsmith-stretch.h>
#include <juce_cryptography/juce_cryptography.h>
#include <cmath>
#include <limits>

namespace emusician::audio {
namespace {
bool cancelled(const IOOptions& io) { return io.cancelled && io.cancelled(); }
juce::Result hash(const juce::File& file, juce::String& out, const IOOptions& io)
{
    auto stream=file.createInputStream(); if(!stream) return juce::Result::fail("Cannot read Warp audio.");
    const auto size=stream->getTotalLength();const auto modified=file.getLastModificationTime();
    struct Input final : juce::InputStream {
        juce::FileInputStream& stream; const IOOptions& io;
        Input(juce::FileInputStream& s,const IOOptions& o):stream(s),io(o){}
        juce::int64 getTotalLength() override{return stream.getTotalLength();}
        juce::int64 getPosition() override{return stream.getPosition();}
        bool setPosition(juce::int64 p) override{return stream.setPosition(p);}
        bool isExhausted() override{return cancelled(io)||stream.isExhausted();}
        int read(void* p,int n) override{return cancelled(io)?0:stream.read(p,n);}
    } input(*stream,io);
    out=juce::SHA256(input).toHexString();
    if(cancelled(io))return juce::Result::fail("Warp cancelled.");
    if(stream->getPosition()!=size||file.getSize()!=size||file.getLastModificationTime()!=modified)
        return juce::Result::fail("Warp source changed during reading.");
    return juce::Result::ok();
}
bool finiteAudio(const juce::AudioBuffer<float>& b,int count)
{
    for(int c=0;c<b.getNumChannels();++c)for(int i=0;i<count;++i)if(!std::isfinite(b.getSample(c,i)))return false;
    return true;
}
}
juce::Result renderWarp(const PreparedSource& original,double speed,WarpRender& result,const IOOptions& io)
{
    using juce::Result;
    if(!std::isfinite(speed)||speed<1.0/15.0-1e-12||speed>15.0+1e-12)return Result::fail("Warp speed is outside the supported 1/15 to 15 range.");
    if(cancelled(io))return Result::fail("Warp cancelled.");
    juce::String sourceHash; if(auto r=hash(original.playbackFile,sourceHash,io);r.failed())return r;
    juce::WavAudioFormat wav;
    auto stream=original.playbackFile.createInputStream();
    std::unique_ptr<juce::AudioFormatReader> reader(stream?wav.createReaderFor(stream.release(),true):nullptr);
    if(!reader||reader->lengthInSamples<=0||reader->numChannels<1||reader->numChannels>2||!std::isfinite(reader->sampleRate)||reader->sampleRate<=0)
        return Result::fail("Warp requires valid prepared mono/stereo PCM.");
    const auto total=reader->lengthInSamples;
    const auto outputFrames=static_cast<juce::int64>(std::llround(double(total)/speed));
    if(outputFrames<=0||outputFrames>(juce::int64(std::numeric_limits<std::uint32_t>::max())-1048576)/(4*reader->numChannels))
        return Result::fail("Warp output is empty or exceeds the 4 GiB WAV limit.");
    const auto keyText=sourceHash+":"+juce::String(speed,17)+":"+warpRendererVersion;
    const auto key=juce::SHA256(keyText.toRawUTF8(),keyText.getNumBytesAsUTF8()).toHexString();
    const auto root=juce::File::getSpecialLocation(juce::File::userApplicationDataDirectory).getChildFile("E-musician/cache/warp-v1");
    if(root.isSymbolicLink())return Result::fail("Warp cache must not be linked.");
    if(auto r=root.createDirectory();r.failed())return r;
    const auto file=root.getChildFile(key+".wav"), receipt=root.getChildFile(key+".json");
    if(file.isSymbolicLink()||receipt.isSymbolicLink())return Result::fail("Warp cache entry must not be linked.");
    juce::String renderHash;
    auto valid=[&](const juce::File& path)->bool{
        auto in=path.createInputStream();std::unique_ptr<juce::AudioFormatReader> check(in?wav.createReaderFor(in.release(),true):nullptr);
        return check&&check->lengthInSamples==outputFrames&&check->numChannels==reader->numChannels&&check->sampleRate==reader->sampleRate;
    };
    const auto saved=juce::JSON::parse(receipt);
    bool hit=saved["key"].toString()==key&&valid(file);
    if(hit){auto r=hash(file,renderHash,io);if(r.failed())return r;hit=renderHash==saved["sha256"].toString();}
    if(!hit){
        juce::TemporaryFile temporary(file);auto out=temporary.getFile().createOutputStream();
        if(!out)return Result::fail("Cannot create Warp cache.");
        std::unique_ptr<juce::AudioFormatWriter> writer(wav.createWriterFor(out.get(),reader->sampleRate,reader->numChannels,32,{},0));
        if(!writer)return Result::fail("Cannot create Warp PCM writer.");out.release();
        const int channels=int(reader->numChannels);
        signalsmith::stretch::SignalsmithStretch<float> stretcher(0);
        stretcher.presetDefault(channels,reader->sampleRate);stretcher.setTransposeFactor(1.0);
        const int inputLatency=stretcher.inputLatency(), outputLatency=stretcher.outputLatency();
        constexpr int block=1024;
        juce::AudioBuffer<float> input(channels,std::max(inputLatency,int(std::ceil(block*speed))+2));
        juce::AudioBuffer<float> output(channels,std::max(block,outputLatency));
        auto read=[&](juce::int64 position,int count){
            input.clear();const int available=int(std::max<juce::int64>(0,std::min<juce::int64>(count,total-position)));
            return (available==0||reader->read(&input,0,available,position,true,true))&&finiteAudio(input,count);
        };
        if(!read(0,inputLatency))return Result::fail("Cannot read Warp pre-roll.");
        stretcher.seek(input.getArrayOfReadPointers(),inputLatency,speed);
        juce::int64 consumed=0, produced=0, written=0;int skip=outputLatency;
        auto write=[&](int count){
            if(!finiteAudio(output,count))return false;
            const int drop=std::min(skip,count);skip-=drop;count-=drop;
            if(count>0){if(!writer->writeFromAudioSampleBuffer(output,drop,count))return false;written+=count;}
            return true;
        };
        while(produced<outputFrames){
            if(cancelled(io))return Result::fail("Warp cancelled.");
            const int nOut=int(std::min<juce::int64>(block,outputFrames-produced));
            const auto end=produced+nOut==outputFrames?total:static_cast<juce::int64>(std::llround(double(produced+nOut)*speed));
            const int nIn=int(end-consumed);
            if(!read(inputLatency+consumed,nIn))return Result::fail("Cannot read complete Warp source.");
            stretcher.process(input.getArrayOfReadPointers(),nIn,output.getArrayOfWritePointers(),nOut);
            if(!write(nOut))return Result::fail("Cannot write finite Warp samples.");
            consumed=end;produced+=nOut;
            if(io.progress)io.progress(double(produced)/double(outputFrames),"Rendering pitch-preserving audio");
        }
        stretcher.flush(output.getArrayOfWritePointers(),outputLatency);
        if(!write(outputLatency)||written!=outputFrames)return Result::fail("Warp latency compensation produced an incorrect length.");
        writer.reset();
        if(!valid(temporary.getFile()))return Result::fail("Warp output verification failed.");
        juce::String after;if(auto r=hash(original.playbackFile,after,io);r.failed())return r;
        if(after!=sourceHash)return Result::fail("Warp source changed during rendering.");
        if(auto r=hash(temporary.getFile(),renderHash,io);r.failed())return r;
        if(cancelled(io))return Result::fail("Warp cancelled.");
        if(!temporary.overwriteTargetFileWithTemporary())return Result::fail("Cannot publish Warp cache.");
        auto* metadata=new juce::DynamicObject();metadata->setProperty("key",key);metadata->setProperty("sha256",renderHash);
        juce::TemporaryFile receiptTemp(receipt);
        if(!receiptTemp.getFile().replaceWithText(juce::JSON::toString(juce::var(metadata)))||!receiptTemp.overwriteTargetFileWithTemporary())
            return Result::fail("Cannot publish verified Warp receipt.");
    }
    result={{file,double(outputFrames)/reader->sampleRate,reader->sampleRate,int(reader->numChannels),"WAV"},sourceHash,renderHash,key,outputFrames};
    if(io.progress)io.progress(1,"Warp ready");
    return Result::ok();
}
}
