#include <juce_audio_processors/juce_audio_processors.h>
#include <juce_audio_processors/utilities/juce_FlagCache.h>
#define JUCE_VST3HEADERS_INCLUDE_HEADERS_ONLY 1
#include <juce_audio_processors/format_types/juce_VST3Headers.h>
#include <juce_audio_processors/format_types/juce_VST3Common.h>
#include <set>
#include <stdexcept>

namespace emusician {
juce::Result runVst3InactiveBusSmoke()
{
    try {
        const auto require = [](bool condition, const char* message) {
            if (!condition) throw std::runtime_error(message);
        };
        const auto verify = [&]<typename Sample>() {
            juce::HostBufferMapper mapper;
            // Keep an active bus after an inactive one: active offsets must not shift.
            mapper.prepare({ juce::ChannelMapping{juce::AudioChannelSet::stereo()},
                             juce::ChannelMapping{juce::AudioChannelSet::stereo(), false},
                             juce::ChannelMapping{juce::AudioChannelSet::mono()},
                             juce::ChannelMapping{juce::AudioChannelSet::stereo(), false} }, 256);
            juce::AudioBuffer<Sample> host(3, 256); host.clear();
            auto pointers = [](const Steinberg::Vst::AudioBusBuffers& bus) {
                if constexpr (std::is_same_v<Sample, float>) return bus.channelBuffers32;
                else return bus.channelBuffers64;
            };
            const auto* buses = mapper.getVst3LayoutForJuceBuffer(host);
            require(buses != nullptr, "Prepared block must be accepted");
            require(pointers(buses[0])[0] == host.getWritePointer(0)
                 && pointers(buses[0])[1] == host.getWritePointer(1)
                 && pointers(buses[2])[0] == host.getWritePointer(2), "Active bus routing changed");
            std::set<Sample*> separate;
            for (int b : {1, 3}) {
                require(buses[b].numChannels == 2 && buses[b].silenceFlags == ~Steinberg::uint64{}, "Inactive bus shape/flags changed");
                for (int c=0;c<2;++c) {
                    auto* p = pointers(buses[b])[c];
                    require(p && separate.insert(p).second, "Inactive channels must have unique writable buffers");
                    for(int n=0;n<256;++n) { require(p[n] == Sample{}, "Inactive input must be silent"); p[n]=Sample(0.75); }
                }
            }
            require(host.getMagnitude(0, 256) == Sample{}, "Discarded output leaked into active audio");
            auto* saved = pointers(buses[1])[0];
            // A misbehaving plugin may write inactive inputs too. Every new block is cleared.
            buses = mapper.getVst3LayoutForJuceBuffer(host);
            require(pointers(buses[1])[0] == saved, "Processing must reuse prepared storage");
            for (int b : {1,3}) for(int c=0;c<2;++c) for(int n=0;n<256;++n)
                require(pointers(buses[b])[c][n] == Sample{}, "Inactive buffers carried prior block audio");
            juce::AudioBuffer<Sample> shorter(3, 37), oversized(3, 257);
            require(mapper.getVst3LayoutForJuceBuffer(shorter) != nullptr, "Variable short blocks rejected");
            require(!mapper.supportsBufferSize(257) && mapper.getVst3LayoutForJuceBuffer(oversized) == nullptr,
                    "Oversized blocks must fail without allocation or buffer overrun");
        };
        verify.template operator()<float>(); verify.template operator()<double>();
        return juce::Result::ok();
    } catch(const std::exception& e) { return juce::Result::fail(e.what()); }
}
}
