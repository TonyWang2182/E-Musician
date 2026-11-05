cmake_minimum_required(VERSION 3.25)
project(EMusician VERSION 0.11.0 LANGUAGES C CXX)
set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_MSVC_RUNTIME_LIBRARY "MultiThreaded$<$<CONFIG:Debug>:Debug>")
set_property(GLOBAL PROPERTY USE_FOLDERS YES)
enable_testing()
find_package(Python3 REQUIRED COMPONENTS Interpreter)
add_test(NAME development.logging COMMAND "${Python3_EXECUTABLE}" -m unittest discover
    -s "${CMAKE_CURRENT_SOURCE_DIR}/tests" -p test_dev_logger.py -v)
add_test(NAME engine.patch_contracts COMMAND "${Python3_EXECUTABLE}" -m unittest discover
    -s "${CMAKE_CURRENT_SOURCE_DIR}/tests" -p test_engine_patches.py -v)

add_executable(emusician_core_tests tests/CoreTests.cpp)
target_include_directories(emusician_core_tests PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}")
if(MSVC)
    target_compile_options(emusician_core_tests PRIVATE /W4 /WX /utf-8)
endif()
add_test(NAME core.contracts COMMAND emusician_core_tests)
add_executable(emusician_sampler_tests tests/NativeSamplerTests.cpp core/NativeSampler.cpp)
target_include_directories(emusician_sampler_tests PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}")
add_test(NAME sampler.dsp COMMAND emusician_sampler_tests)
add_executable(emusician_effects_tests tests/NativeEffectsTests.cpp core/NativeEffects.cpp)
add_executable(emusician_reverb_tests tests/NativeReverbTests.cpp core/NativeReverb.cpp)
add_executable(emusician_autofilter_tests tests/NativeAutoFilterTests.cpp core/NativeAutoFilter.cpp)
target_include_directories(emusician_autofilter_tests PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}")
add_test(NAME autofilter.dsp COMMAND emusician_autofilter_tests)
target_include_directories(emusician_reverb_tests PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}")
add_test(NAME reverb.dsp COMMAND emusician_reverb_tests)
target_include_directories(emusician_effects_tests PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}")
add_test(NAME effects.dsp COMMAND emusician_effects_tests)
add_executable(emusician_effects_benchmark tests/NativeEffectsBenchmark.cpp core/NativeEffects.cpp)
target_include_directories(emusician_effects_benchmark PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}")

option(EMUSICIAN_BUILD_DESKTOP "Build the JUCE/Tracktion desktop application" ON)
option(EMUSICIAN_BUILD_UPSTREAM_DEMO "Also make the upstream DemoRunner target available" OFF)
if(EMUSICIAN_BUILD_DESKTOP)
    set(ENGINE_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/.cache/monitor-engine")
    if(NOT EXISTS "${ENGINE_ROOT}/modules/juce/CMakeLists.txt")
        message(FATAL_ERROR "Dependencies missing. Run: python scripts/dev.py bootstrap")
    endif()
    find_package(Git REQUIRED)
    file(READ "${CMAKE_CURRENT_SOURCE_DIR}/cmake/dependencies.json" DEPENDENCIES)
    foreach(DEP IN ITEMS tracktion juce)
        string(JSON EXPECTED_COMMIT GET "${DEPENDENCIES}" ${DEP} commit)
        if(DEP STREQUAL "tracktion")
            set(DEP_DIR "${ENGINE_ROOT}")
        else()
            set(DEP_DIR "${ENGINE_ROOT}/modules/juce")
        endif()
        execute_process(COMMAND "${GIT_EXECUTABLE}" -C "${DEP_DIR}" rev-parse HEAD
            OUTPUT_VARIABLE ACTUAL_COMMIT OUTPUT_STRIP_TRAILING_WHITESPACE COMMAND_ERROR_IS_FATAL ANY)
        if(NOT ACTUAL_COMMIT STREQUAL EXPECTED_COMMIT)
            message(FATAL_ERROR "${DEP} commit differs from cmake/dependencies.json")
        endif()
    endforeach()
    execute_process(COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/scripts/apply_engine_patches.py" verify --engine-root "${ENGINE_ROOT}"
        RESULT_VARIABLE ENGINE_PATCH_RESULT OUTPUT_VARIABLE ENGINE_PATCH_OUTPUT ERROR_VARIABLE ENGINE_PATCH_ERROR)
    if(NOT ENGINE_PATCH_RESULT EQUAL 0)
        message(FATAL_ERROR "Tracktion source patch is missing or changed. Run python scripts/dev.py bootstrap. ${ENGINE_PATCH_ERROR}")
    endif()
    if(WIN32)
        file(READ "${CMAKE_CURRENT_SOURCE_DIR}/cmake/webview2.json" WEBVIEW_MANIFEST)
        string(JSON WEBVIEW_VERSION GET "${WEBVIEW_MANIFEST}" version)
        set(JUCE_WEBVIEW2_PACKAGE_LOCATION "${CMAKE_CURRENT_SOURCE_DIR}/.cache/webview2" CACHE PATH "Pinned WebView2 SDK root")
        set(WEBVIEW_SDK "${JUCE_WEBVIEW2_PACKAGE_LOCATION}/Microsoft.Web.WebView2.${WEBVIEW_VERSION}")
        foreach(WEBVIEW_ITEM IN ITEMS header x64_library)
            if(WEBVIEW_ITEM STREQUAL "header")
                set(WEBVIEW_FILE "${WEBVIEW_SDK}/build/native/include/WebView2.h")
            else()
                set(WEBVIEW_FILE "${WEBVIEW_SDK}/build/native/x64/WebView2LoaderStatic.lib")
            endif()
            if(NOT EXISTS "${WEBVIEW_FILE}")
                message(FATAL_ERROR "Pinned WebView2 SDK missing. Run python scripts/bootstrap_webview2.py")
            endif()
            file(SHA256 "${WEBVIEW_FILE}" WEBVIEW_HASH)
            string(JSON WEBVIEW_EXPECTED GET "${WEBVIEW_MANIFEST}" "${WEBVIEW_ITEM}_sha256")
            if(NOT WEBVIEW_HASH STREQUAL WEBVIEW_EXPECTED)
                message(FATAL_ERROR "Pinned WebView2 SDK hash mismatch")
            endif()
        endforeach()
    endif()
    add_subdirectory("${ENGINE_ROOT}/modules/juce" "dependencies/juce")
    set(EMUSICIAN_VST2_SDK "${CMAKE_CURRENT_SOURCE_DIR}/_deps/vst2_sdk" CACHE PATH "Local VST2 interface headers")
    if(NOT EXISTS "${EMUSICIAN_VST2_SDK}/pluginterfaces/vst2.x/aeffect.h")
        message(FATAL_ERROR "VST2 interfaces missing. Run python scripts/bootstrap_vst2.py before configuring.")
    endif()
    juce_set_vst2_sdk_path("${EMUSICIAN_VST2_SDK}")
    execute_process(COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/scripts/bootstrap_asio.py" --verify-only
        RESULT_VARIABLE ASIO_VERIFY_RESULT OUTPUT_VARIABLE ASIO_VERIFY_OUTPUT ERROR_VARIABLE ASIO_VERIFY_ERROR)
    if(NOT ASIO_VERIFY_RESULT EQUAL 0)
        message(FATAL_ERROR "ASIO interfaces missing or changed. Run python scripts/dev.py bootstrap. ${ASIO_VERIFY_ERROR}")
    endif()
    execute_process(COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/scripts/bootstrap_stretch.py" --verify-only
        RESULT_VARIABLE STRETCH_VERIFY_RESULT OUTPUT_VARIABLE STRETCH_VERIFY_OUTPUT ERROR_VARIABLE STRETCH_VERIFY_ERROR)
    if(NOT STRETCH_VERIFY_RESULT EQUAL 0)
        message(FATAL_ERROR "Pinned Signalsmith dependencies missing or changed. Run python scripts/bootstrap_stretch.py. ${STRETCH_VERIFY_ERROR}")
    endif()
    add_subdirectory("${ENGINE_ROOT}/modules" "dependencies/tracktion")
    add_executable(emusician_native_instrument_tests tests/NativeInstrumentTests.cpp
        apps/desktop/NativeInstrument.cpp core/NativeSampler.cpp)
    target_include_directories(emusician_native_instrument_tests PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}" "${CMAKE_CURRENT_SOURCE_DIR}/_deps/asio_sdk/common" "${CMAKE_CURRENT_SOURCE_DIR}/_deps/vst2_sdk")
    target_compile_definitions(emusician_native_instrument_tests PRIVATE JUCE_USE_CURL=0 JUCE_USE_MP3AUDIOFORMAT=1
        JUCE_PLUGINHOST_VST3=1 JUCE_PLUGINHOST_VST=1 JUCE_ASIO=1 TRACKTION_ENABLE_TIMESTRETCH_SOUNDTOUCH=0)
    target_link_libraries(emusician_native_instrument_tests PRIVATE tracktion::tracktion_engine tracktion::tracktion_graph
        tracktion::tracktion_core juce::juce_audio_utils juce::juce_cryptography juce::juce_dsp juce::juce_recommended_config_flags)
    if(MSVC)
        target_compile_options(emusician_native_instrument_tests PRIVATE /utf-8 /bigobj)
    endif()
    add_test(NAME native_instrument.contracts COMMAND emusician_native_instrument_tests)
    juce_add_binary_data(EMusicianBrand NAMESPACE emusician_brand HEADER_NAME BrandAssets.h
        SOURCES assets/brand/yi-yue-shi-logo.png)
    juce_add_gui_app(EMusician PRODUCT_NAME "E-musician" COMPANY_NAME "E-musician"
        BUNDLE_ID "local.emusician.desktop" NEEDS_WEBVIEW2 TRUE
        ICON_BIG "${CMAKE_CURRENT_SOURCE_DIR}/assets/brand/yi-yue-shi-logo.png"
        ICON_SMALL "${CMAKE_CURRENT_SOURCE_DIR}/assets/brand/yi-yue-shi-logo.png")
    target_link_libraries(EMusician PRIVATE EMusicianBrand)
    if(WIN32)
        # JUCE 8.0.6 omits its Info.txt dependency for generated Windows resources.
        # Keep Explorer's file/product version current on incremental builds.
        get_target_property(EMUSICIAN_GENERATED_DIR EMusician JUCE_GENERATED_SOURCES_DIRECTORY)
        get_target_property(EMUSICIAN_INFO_FILE EMusician JUCE_INFO_FILE)
        add_custom_command(OUTPUT "${EMUSICIAN_GENERATED_DIR}/EMusician_resources.rc"
            APPEND DEPENDS "${EMUSICIAN_INFO_FILE}")
    endif()
    target_sources(EMusician PRIVATE apps/desktop/Main.cpp apps/desktop/EngineSession.cpp apps/desktop/NativeDevicePanel.cpp apps/desktop/SampleWaveform.cpp apps/desktop/NativeInstrument.cpp apps/desktop/NativeLoadQueue.cpp core/NativeSampler.cpp apps/desktop/NativeEffects.cpp apps/desktop/NativeEffectsPanel.cpp core/NativeEffects.cpp core/NativeReverb.cpp core/NativeAutoFilter.cpp
        apps/desktop/AnalysisPreview.cpp apps/desktop/AnalysisPanel.cpp apps/desktop/MainComponent.cpp apps/desktop/AgentSidebar.cpp apps/desktop/ArrangementView.cpp
        apps/desktop/ProjectStorage.cpp apps/desktop/AudioSource.cpp apps/desktop/AudioWarp.cpp apps/desktop/PluginHost.cpp
        apps/desktop/PianoRoll.cpp apps/desktop/ControlServer.cpp apps/desktop/SelectedTrackPanel.cpp tests/Vst3InactiveBusSmoke.cpp)
    # Keep the application-reported version and window title tied to the build version.
    set_property(SOURCE apps/desktop/Main.cpp APPEND PROPERTY COMPILE_DEFINITIONS
        "EMUSICIAN_APPLICATION_VERSION=\"${PROJECT_VERSION}\"")
    target_include_directories(EMusician PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}" "${CMAKE_CURRENT_SOURCE_DIR}/_deps/asio_sdk/common")
    target_include_directories(EMusician PRIVATE
        "${CMAKE_CURRENT_SOURCE_DIR}/_deps/signalsmith-stretch/include"
        "${CMAKE_CURRENT_SOURCE_DIR}/_deps/signalsmith-linear/include")
    target_compile_definitions(EMusician PRIVATE
        EMUSICIAN_SOURCE_DIR="${CMAKE_CURRENT_SOURCE_DIR}"
        EMUSICIAN_AGENT_PYTHON="${Python3_EXECUTABLE}"
        JUCE_USE_WIN_WEBVIEW2=1 JUCE_USE_WIN_WEBVIEW2_WITH_STATIC_LINKING=1 JUCE_WEB_BROWSER=1 JUCE_USE_CURL=0 JUCE_USE_MP3AUDIOFORMAT=1
        JUCE_PLUGINHOST_VST3=1 JUCE_PLUGINHOST_VST=1 JUCE_ASIO=1
        JUCE_MODAL_LOOPS_PERMITTED=1 TRACKTION_ENABLE_TIMESTRETCH_SOUNDTOUCH=0)
    if(MSVC)
        target_compile_options(EMusician PRIVATE /utf-8 /bigobj $<$<CONFIG:Release>:/Zi>)
        target_link_options(EMusician PRIVATE $<$<CONFIG:Release>:/DEBUG:FULL>
            $<$<CONFIG:Release>:/OPT:REF> $<$<CONFIG:Release>:/OPT:ICF>)
    endif()
    target_link_libraries(EMusician PRIVATE tracktion::tracktion_engine tracktion::tracktion_graph
        tracktion::tracktion_core juce::juce_audio_utils juce::juce_cryptography juce::juce_recommended_config_flags)
    if(WIN32)
        target_link_libraries(EMusician PRIVATE bcrypt)
    endif()
    set(EMUSICIAN_RUNTIME_OUTPUT_ROOT "${CMAKE_BINARY_DIR}/bin" CACHE PATH "Desktop output root; separate candidates may coexist")
    set_target_properties(EMusician PROPERTIES OUTPUT_NAME "E-musician"
        RUNTIME_OUTPUT_DIRECTORY "${EMUSICIAN_RUNTIME_OUTPUT_ROOT}/$<CONFIG>")
    # Keep legacy recovery fixture paths below Win32 copy limits, independent
    # of nested build names. RunEngineSmoke still creates a fresh UUID each run.
    add_test(NAME engine.integration_smoke COMMAND "${Python3_EXECUTABLE}"
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/RunEngineSmoke.py"
        "$<TARGET_FILE:EMusician>" "${CMAKE_CURRENT_SOURCE_DIR}/build/smoke/$<CONFIG>")
    set_tests_properties(engine.integration_smoke PROPERTIES TIMEOUT 260 RUN_SERIAL TRUE)
    add_test(NAME workspace.brand_colour COMMAND "${Python3_EXECUTABLE}"
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/RunWorkspaceSmoke.py"
        "$<TARGET_FILE:EMusician>" "${CMAKE_CURRENT_SOURCE_DIR}/build/workspace-smoke")
    set_tests_properties(workspace.brand_colour PROPERTIES TIMEOUT 150 RUN_SERIAL TRUE)
    if(WIN32)
        add_test(NAME control.output_isolation COMMAND "${Python3_EXECUTABLE}"
            "${CMAKE_CURRENT_SOURCE_DIR}/tests/ControlOutputSmoke.py"
            "--exe" "$<TARGET_FILE:EMusician>")
        set_tests_properties(control.output_isolation PROPERTIES TIMEOUT 35 RUN_SERIAL TRUE)
    endif()
    if(EMUSICIAN_BUILD_UPSTREAM_DEMO)
        add_subdirectory("${ENGINE_ROOT}/examples/DemoRunner" "upstream-demo" EXCLUDE_FROM_ALL)
    endif()
endif()
