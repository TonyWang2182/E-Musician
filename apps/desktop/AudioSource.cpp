#include "AudioSource.h"
#include <juce_cryptography/juce_cryptography.h>
#include <array>
#include <cmath>
#include <cstdint>
#include <limits>

namespace emusician::audio {
namespace {
using juce::File;
using juce::Result;
using juce::String;
bool isCancelled(const IOOptions& options) { return options.cancelled && options.cancelled(); }
void reportProgress(const IOOptions& options, double fraction, const String& stage)
{ if (options.progress) options.progress(juce::jlimit(0.0, 1.0, fraction), stage); }

struct MP3Layout {
    juce::int64 samples = 0, frames = 0;
    int sampleRate = 0, channels = 0;
    bool skipsInfoFrame = false;
};

bool readAt(juce::FileInputStream& stream, juce::int64 offset, void* bytes, int count)
{
    return offset >= 0 && stream.setPosition(offset) && stream.read(bytes, count) == count;
}
std::uint32_t big32(const unsigned char* bytes)
{
    return std::uint32_t(bytes[0]) << 24 | std::uint32_t(bytes[1]) << 16
         | std::uint32_t(bytes[2]) << 8 | std::uint32_t(bytes[3]);
}
std::uint32_t little32(const unsigned char* bytes)
{
    return std::uint32_t(bytes[3]) << 24 | std::uint32_t(bytes[2]) << 16
         | std::uint32_t(bytes[1]) << 8 | std::uint32_t(bytes[0]);
}
bool startsWith(const unsigned char* bytes, const char* signature, std::size_t size)
{
    return std::memcmp(bytes, signature, size) == 0;
}

Result skipID3(juce::FileInputStream& stream, juce::int64& offset, juce::int64 end)
{
    std::array<unsigned char, 10> header {};
    if (end - offset < 10 || !readAt(stream, offset, header.data(), int(header.size())))
        return Result::fail("The MP3 ID3 header is truncated.");
    if (header[3] < 2 || header[3] > 4 || header[4] == 255
        || ((header[6] | header[7] | header[8] | header[9]) & 128) != 0)
        return Result::fail("The MP3 has an invalid or unsupported ID3 header.");
    const juce::int64 size = (juce::int64(header[6]) << 21) | (juce::int64(header[7]) << 14)
                          | (juce::int64(header[8]) << 7) | header[9];
    const juce::int64 footer = header[3] == 4 && (header[5] & 16) != 0 ? 10 : 0;
    constexpr juce::int64 metadataLimit = 32 * 1024 * 1024;
    if (size > metadataLimit || size + 10 + footer > end - offset)
        return Result::fail("MP3 metadata is truncated or larger than the 32 MiB import limit.");
    offset += size + 10 + footer;
    return Result::ok();
}

Result scanMP3(const File& file, MP3Layout& output, const IOOptions& options)
{
    auto stream = file.createInputStream();
    if (!stream) return Result::fail("The MP3 file cannot be opened.");
    juce::int64 end = stream->getTotalLength(), offset = 0;
    if (end < 4) return Result::fail("The MP3 file is empty or truncated.");
    // Remove recognised trailers from the scan range. Never trust a footer size
    // until it is checked against the remaining file length.
    for (int pass = 0; pass < 4; ++pass) {
        std::array<unsigned char, 32> footer {};
        std::array<unsigned char, 3> tag {};
        if (end >= 128 && readAt(*stream, end - 128, tag.data(), 3) && startsWith(tag.data(), "TAG", 3)) {
            end -= 128;
            continue;
        }
        if (end >= 32 && readAt(*stream, end - 32, footer.data(), 32) && startsWith(footer.data(), "APETAGEX", 8)) {
            const auto version = little32(footer.data() + 8);
            const juce::int64 size = little32(footer.data() + 12);
            const bool hasHeader = (little32(footer.data() + 20) & 0x80000000u) != 0;
            const auto total = size + (hasHeader ? 32 : 0);
            if ((version != 1000 && version != 2000) || size < 32 || total > end || total > 32 * 1024 * 1024)
                return Result::fail("The MP3 APE metadata is invalid or too large.");
            if (hasHeader) {
                std::array<unsigned char, 8> signature {};
                if (!readAt(*stream, end - total, signature.data(), 8) || !startsWith(signature.data(), "APETAGEX", 8))
                    return Result::fail("The MP3 APE header is missing.");
            }
            end -= total;
            continue;
        }
        break;
    }
    for (;;) {
        std::array<unsigned char, 3> signature {};
        if (end - offset < 3 || !readAt(*stream, offset, signature.data(), 3) || !startsWith(signature.data(), "ID3", 3)) break;
        if (auto result = skipID3(*stream, offset, end); result.failed()) return result;
    }

    MP3Layout layout;
    constexpr int bitratesMpeg1[] { 0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0 };
    constexpr int bitratesLow[] { 0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0 };
    constexpr int rates[] { 44100, 48000, 32000 };
    int initialVersion = -1;
    while (offset < end) {
        if (isCancelled(options)) return Result::fail("Audio preparation cancelled.");
        if ((layout.frames & 1023) == 0) reportProgress(options, 0.15 + 0.10 * double(offset) / double(end), "Scanning MP3 frames");
        std::array<unsigned char, 4> bytes {};
        if (end - offset < 4 || !readAt(*stream, offset, bytes.data(), 4))
            return Result::fail("The MP3 ends with a truncated frame.");
        // ID3v2 is also allowed after the complete audio stream.
        if (startsWith(bytes.data(), "ID3", 3)) {
            if (auto result = skipID3(*stream, offset, end); result.failed()) return result;
            if (offset != end) return Result::fail("Unexpected data follows the trailing MP3 tag.");
            break;
        }
        const auto header = big32(bytes.data());
        const int version = int((header >> 19) & 3), layer = int((header >> 17) & 3);
        const int bitrateIndex = int((header >> 12) & 15), rateIndex = int((header >> 10) & 3);
        if ((header & 0xffe00000u) != 0xffe00000u || version == 1 || layer != 1
            || bitrateIndex == 15 || rateIndex == 3 || (header & 3) == 2)
            return Result::fail("The MP3 contains an invalid Layer III frame at byte " + String(offset) + ".");
        if (bitrateIndex == 0)
            return Result::fail("Free-format MP3 is not supported. Use standard CBR or VBR MP3.");
        const int rate = rates[rateIndex] / (version == 3 ? 1 : version == 2 ? 2 : 4);
        const int channels = ((header >> 6) & 3) == 3 ? 1 : 2;
        const int samples = version == 3 ? 1152 : 576;
        const int bitrate = version == 3 ? bitratesMpeg1[bitrateIndex] : bitratesLow[bitrateIndex];
        const int frameSize = (version == 3 ? 144000 : 72000) * bitrate / rate + int((header >> 9) & 1);
        if (frameSize < 4 || frameSize > end - offset)
            return Result::fail("The MP3 contains a truncated audio frame.");
        if (layout.frames == 0) {
            layout.sampleRate = rate; layout.channels = channels; initialVersion = version;
            // The pinned JUCE decoder skips Xing/Info's entire first frame.
            // Mirror its tag offset (without trusting the advertised frame count).
            const int tagOffset = 4 + (version == 3 ? (channels == 1 ? 17 : 32) : (channels == 1 ? 9 : 17));
            std::array<unsigned char, 4> tag {};
            layout.skipsInfoFrame = frameSize >= tagOffset + 4
                && readAt(*stream, offset + tagOffset, tag.data(), 4)
                && (startsWith(tag.data(), "Xing", 4) || startsWith(tag.data(), "Info", 4));
        } else if (rate != layout.sampleRate || channels != layout.channels || version != initialVersion) {
            return Result::fail("MP3 streams that change sample rate, channels, or MPEG version are not supported.");
        }
        if (!(layout.frames == 0 && layout.skipsInfoFrame)) layout.samples += samples;
        ++layout.frames;
        offset += frameSize;
        // Standard RIFF/WAV cache entries must stay below their 32-bit size limit.
        if (layout.samples > (juce::int64(std::numeric_limits<std::uint32_t>::max()) - 1024 * 1024) / (3 * channels))
            return Result::fail("Decoded MP3 exceeds this version's 4 GiB PCM-cache limit.");
    }
    if (layout.samples <= 0 || layout.frames == 0 || stream->getStatus().failed())
        return Result::fail("The file does not contain a complete MP3 audio stream.");
    output = layout;
    return Result::ok();
}

bool finite(const juce::AudioBuffer<float>& buffer, int count)
{
    for (int channel = 0; channel < buffer.getNumChannels(); ++channel)
        for (int sample = 0; sample < count; ++sample)
            if (!std::isfinite(buffer.getSample(channel, sample))) return false;
    return true;
}
bool probe(juce::AudioFormatReader& reader)
{
    if (reader.sampleRate <= 0 || !std::isfinite(reader.sampleRate) || reader.lengthInSamples <= 0
        || reader.numChannels < 1 || reader.numChannels > 2) return false;
    const auto count = int(juce::jmin<juce::int64>(4096, reader.lengthInSamples));
    juce::AudioBuffer<float> block(int(reader.numChannels), count);
    if (!reader.read(&block, 0, count, 0, true, true) || !finite(block, count)) return false;
    return reader.read(&block, 0, count, reader.lengthInSamples - count, true, true) && finite(block, count);
}
bool validCache(const File& file, const MP3Layout& layout)
{
    if (!file.existsAsFile() || file.isSymbolicLink()
        || file.getSize() < layout.samples * layout.channels * 3 + 44) return false;
    juce::WavAudioFormat wav;
    auto stream = file.createInputStream();
    if (!stream) return false;
    std::unique_ptr<juce::AudioFormatReader> reader(wav.createReaderFor(stream.release(), true));
    return reader != nullptr && reader->sampleRate == layout.sampleRate && int(reader->numChannels) == layout.channels
        && reader->lengthInSamples == layout.samples && reader->bitsPerSample == 24 && probe(*reader);
}
Result hashFile(const File& file, String& result, const IOOptions& options, double from, double width)
{
    auto stream = file.createInputStream();
    if (!stream) return Result::fail("Cannot read the source audio for cache validation.");
    const auto size = stream->getTotalLength();
    struct MonitoredStream final : juce::InputStream {
        juce::FileInputStream& source;
        const IOOptions& options;
        double from, width;
        juce::int64 nextReport = 0;
        MonitoredStream(juce::FileInputStream& s, const IOOptions& o, double f, double w) : source(s), options(o), from(f), width(w) {}
        juce::int64 getTotalLength() override { return source.getTotalLength(); }
        juce::int64 getPosition() override { return source.getPosition(); }
        bool setPosition(juce::int64 p) override { return source.setPosition(p); }
        bool isExhausted() override { return isCancelled(options) || source.isExhausted(); }
        int read(void* data, int maximum) override {
            if (isCancelled(options)) return 0;
            const int read = source.read(data, maximum);
            if (source.getPosition() >= nextReport) {
                reportProgress(options, from + width * double(source.getPosition()) / double(juce::jmax<juce::int64>(1, source.getTotalLength())), "Checking audio source");
                nextReport = source.getPosition() + 1024 * 1024;
            }
            return read;
        }
    } monitored(*stream, options, from, width);
    const auto hash = juce::SHA256(monitored).toHexString();
    if (isCancelled(options)) return Result::fail("Audio preparation cancelled.");
    if (size <= 0 || stream->getStatus().failed() || stream->getPosition() != size)
        return Result::fail("The source audio changed or could not be completely read.");
    result = hash;
    return Result::ok();
}
} // namespace

Result prepareSource(const File& file, PreparedSource& result, const IOOptions& options)
{
    if (isCancelled(options)) return Result::fail("Audio preparation cancelled.");
    if (!file.existsAsFile() || !file.hasFileExtension("wav;mp3"))
        return Result::fail("Choose an existing WAV or MP3 audio file.");
    if (file.hasFileExtension("wav")) {
        juce::WavAudioFormat wav;
        auto stream = file.createInputStream();
        if (!stream) return Result::fail("The WAV file cannot be opened.");
        std::unique_ptr<juce::AudioFormatReader> reader(wav.createReaderFor(stream.release(), true));
        if (!reader || !probe(*reader)) return Result::fail("The WAV audio is empty, damaged, or not mono/stereo.");
        if (isCancelled(options)) return Result::fail("Audio preparation cancelled.");
        result = { file, double(reader->lengthInSamples) / reader->sampleRate,
                   reader->sampleRate, int(reader->numChannels), "WAV" };
        reportProgress(options, 1.0, "Audio ready");
        return Result::ok();
    }

    // Only MP3 decoding needs a PCM cache. An explicit root must never be
    // resolved against the working directory or silently fall back to C:.
    const auto configuredRoot=juce::SystemStats::getEnvironmentVariable("EMUSICIAN_AUDIO_CACHE_ROOT",{});
    if(configuredRoot.isNotEmpty()&&!File::isAbsolutePath(configuredRoot))return Result::fail("EMUSICIAN_AUDIO_CACHE_ROOT must be an absolute directory path.");
    const auto cacheRoot=configuredRoot.isEmpty()?File::getSpecialLocation(File::userApplicationDataDirectory).getChildFile("E-musician/cache"):File(configuredRoot);
    const auto cacheDirectory=cacheRoot.getChildFile("audio-v1");
    if(cacheRoot.isSymbolicLink()||cacheDirectory.isSymbolicLink())return Result::fail("The audio cache cannot be a linked folder.");
    String hash;
    if (auto r = hashFile(file, hash, options, 0.0, 0.15); r.failed()) return r;
    MP3Layout layout;
    if (auto r = scanMP3(file, layout, options); r.failed()) return r;
    if (auto r = cacheDirectory.createDirectory(); r.failed()) return Result::fail("Cannot create audio cache: " + r.getErrorMessage());
    const auto cache = cacheDirectory.getChildFile(hash + ".wav");
    if (cache.isSymbolicLink() || cache.isDirectory()) return Result::fail("The audio cache entry is not a regular file.");
    if (!validCache(cache, layout)) {
        juce::MP3AudioFormat mp3;
        auto input = file.createInputStream();
        if (!input) return Result::fail("The MP3 file cannot be opened for decoding.");
        std::unique_ptr<juce::AudioFormatReader> reader(mp3.createReaderFor(input.release(), true));
        if (!reader || reader->sampleRate != layout.sampleRate || int(reader->numChannels) != layout.channels)
            return Result::fail("The MP3 decoder could not read the validated stream.");
        // JUCE 8.0.6 estimates untagged VBR length from the first frame bitrate.
        // The complete frame scan is authoritative. Decode sequentially so its
        // approximate MP3 seeking is never used for application playback.
        reader->lengthInSamples = layout.samples;
        juce::TemporaryFile temporary(cache);
        auto output = temporary.getFile().createOutputStream();
        if (!output) return Result::fail("Cannot create the decoded audio cache file.");
        juce::WavAudioFormat wav;
        std::unique_ptr<juce::AudioFormatWriter> writer(wav.createWriterFor(output.get(), layout.sampleRate,
            static_cast<unsigned int>(layout.channels), 24, {}, 0));
        if (!writer) return Result::fail("Cannot create the PCM cache writer.");
        output.release();
        constexpr int blockSize = 8192;
        juce::AudioBuffer<float> block(layout.channels, blockSize);
        for (juce::int64 position = 0; position < layout.samples;) {
            if (isCancelled(options)) return Result::fail("Audio preparation cancelled.");
            const int count = int(juce::jmin<juce::int64>(blockSize, layout.samples - position));
            if (!reader->read(&block, 0, count, position, true, true) || !finite(block, count))
                return Result::fail("The MP3 could not be completely decoded to finite audio samples.");
            if (!writer->writeFromAudioSampleBuffer(block, 0, count))
                return Result::fail("The decoded audio cache could not be written. Check free disk space.");
            position += count;
            reportProgress(options, 0.25 + 0.65 * double(position) / double(layout.samples), "Decoding MP3");
        }
        writer.reset();
        if (!validCache(temporary.getFile(), layout)) return Result::fail("Decoded PCM cache verification failed.");
        String finalHash;
        if (auto r = hashFile(file, finalHash, options, 0.90, 0.10); r.failed()) return r;
        if (finalHash != hash) return Result::fail("The MP3 changed during import. Try importing it again.");
        if (isCancelled(options)) return Result::fail("Audio preparation cancelled.");
        if (!temporary.overwriteTargetFileWithTemporary()) return Result::fail("Cannot commit the decoded audio cache.");
    }
    if (isCancelled(options)) return Result::fail("Audio preparation cancelled.");
    result = { cache, double(layout.samples) / layout.sampleRate, double(layout.sampleRate), layout.channels, "MP3" };
    reportProgress(options, 1.0, "Audio ready");
    return Result::ok();
}
} // namespace emusician::audio
