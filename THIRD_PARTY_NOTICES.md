# Third-party notices

E-musician's original code is licensed under the GNU Affero General Public
License, version 3, in [LICENSE](LICENSE). Third-party code retains its own
copyright and license. The dependency versions below are the pinned versions
used by this repository, rather than a statement about newer upstream releases.

## Native build dependencies

| Component | Pinned source | Terms in the pinned source | Retained notice |
| --- | --- | --- | --- |
| Tracktion Engine 3.2.0 | [b0c7dd090a56b27fe01bb394617891906eb34daf](https://github.com/Tracktion/tracktion_engine/tree/b0c7dd090a56b27fe01bb394617891906eb34daf) | GPLv3 or later, or separate commercial terms | [Tracktion](docs/licenses/tracktion/LICENSE.md) |
| JUCE 8.0.6 | [19edd538429c93d277bf95b55aaa7e3eb545f951](https://github.com/juce-framework/JUCE/tree/19edd538429c93d277bf95b55aaa7e3eb545f951) | AGPLv3, or separate commercial terms | [JUCE](docs/licenses/juce/LICENSE.md) |
| VST3 SDK bundled with that JUCE commit | [Pinned SDK](https://github.com/juce-framework/JUCE/tree/19edd538429c93d277bf95b55aaa7e3eb545f951/modules/juce_audio_processors/format_types/VST3_SDK) | GPLv3 alternative or Steinberg proprietary license; the pinned SDK is not labeled MIT | [SDK](docs/licenses/vst3/LICENSE.txt), [base](docs/licenses/vst3/base-LICENSE.txt), [interfaces](docs/licenses/vst3/pluginterfaces-LICENSE.txt), [public SDK](docs/licenses/vst3/public-sdk-LICENSE.txt) |
| ASIO SDK 2.3.4, 2025-10-15 archive | [Official archive](https://download.steinberg.net/sdk_downloads/ASIO-SDK_2.3.4_2025-10-15.zip) | GPLv3 alternative or Steinberg proprietary license | [ASIO](docs/licenses/asio/LICENSE.txt) |
| Signalsmith Stretch 1.3.2 | [88061fd4eda56a2353c5d65c74aa3f4ccf76f9da](https://github.com/Signalsmith-Audio/signalsmith-stretch/tree/88061fd4eda56a2353c5d65c74aa3f4ccf76f9da) | MIT | [Stretch](docs/licenses/signalsmith/stretch-LICENSE.txt) |
| Signalsmith Linear 0.6.6 | [7bb1c8f36794d6980080ce817c91f8da8fe56a66](https://github.com/Signalsmith-Audio/linear/tree/7bb1c8f36794d6980080ce817c91f8da8fe56a66) | MIT | [Linear](docs/licenses/signalsmith/linear-LICENSE.txt) |
| Microsoft WebView2 SDK 1.0.2903.40 | [Pinned NuGet package](https://www.nuget.org/packages/Microsoft.Web.WebView2/1.0.2903.40) | Microsoft SDK copyright notice and BSD-style redistribution conditions, plus included third-party notices | [License](docs/licenses/webview2/LICENSE.txt), [notices](docs/licenses/webview2/NOTICE.txt) |

The open-source build uses the open-source alternatives identified above.
The full [GPLv3 text](docs/licenses/GPL-3.0.txt) is retained in addition to the
project's AGPLv3 text. Component names and logos remain the property of their
respective owners; inclusion does not imply endorsement.

Exact native dependency commits, archive hashes and source-file hashes are in
[dependencies.json](cmake/dependencies.json), [signalsmith.json](cmake/signalsmith.json)
and [webview2.json](cmake/webview2.json). The copied upstream license files are
byte-preserved, with source-relative paths and hashes in
[UPSTREAM_SOURCES.json](docs/licenses/UPSTREAM_SOURCES.json). License copies
retain the links and references in their original upstream text.

JUCE and Tracktion also include smaller third-party components. The retained
notices cover CHOC, Crill, FLAC, Ogg/Vorbis, JPEG, PNG, HarfBuzz, SheenBidi and
zlib, with additional source-header notices under `docs/licenses/tracktion/`.
Their original source headers remain present in the pinned dependency checkouts.
See the upstream JUCE license's dependency inventory for components used only
by other platforms, optional modules or examples. E-musician's JPEG support is
based in part on the work of the Independent JPEG Group.

## Optional software and model environments

VST2 support is disabled by default. No VST2 SDK headers are downloaded or
distributed by this repository. An optional local build can use a separately
licensed, user-supplied SDK; the public package script rejects VST2 builds.
Installed plugins, audio drivers, instruments and sample libraries are supplied
by the user and are not redistributed.

The WebView2 SDK and the separately installed Microsoft Edge WebView2 Runtime
are different distributions. The portable package includes the compiled loader
and the SDK notices; it does not bundle or install the WebView2 Runtime.
The separately installed runtime remains subject to
[Microsoft's runtime distribution terms](https://developer.microsoft.com/microsoft-edge/webview2/).

Python is installed separately and is not bundled. Optional local analysis and
remote model services have their own code, dependency and model-weight terms.
The main application license does not relicense those weights. No model weights,
commercial sample libraries, API credentials or remote-service access are
included in the public runtime package. See [model setup](docs/MODELS.md) for
the optional provider boundary and installation instructions.

## Test and brand assets

The synthetic MP3 fixtures in `tests/fixtures/audio/` are original generated
signals dedicated under CC0-1.0; see [their notice](tests/fixtures/AUDIO-LICENSE.txt).
The optional fixture-generation tool has a separate retained license under
`tests/fixtures/tool-licenses/` and is not linked into the application.
The project brand image is an original project asset, rather than an upstream
dependency logo. Its provenance is recorded in [assets/brand/README.md](assets/brand/README.md).
