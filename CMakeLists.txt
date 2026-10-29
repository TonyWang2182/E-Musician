cmake_minimum_required(VERSION 3.25)
project(EMusician VERSION 0.6.0 LANGUAGES C CXX)
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

option(EMUSICIAN_BUILD_DESKTOP "Build the JUCE/Tracktion desktop application" ON)
option(EMUSICIAN_BUILD_UPSTREAM_DEMO "Also make the upstream DemoRunner target available" OFF)
if(EMUSICIAN_BUILD_DESKTOP)
    set(ENGINE_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/_deps/tracktion_engine")
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
    execute_process(COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/scripts/apply_engine_patches.py" verify
        RESULT_VARIABLE ENGINE_PATCH_RESULT OUTPUT_VARIABLE ENGINE_PATCH_OUTPUT ERROR_VARIABLE ENGINE_PATCH_ERROR)
    if(NOT ENGINE_PATCH_RESULT EQUAL 0)
        message(FATAL_ERROR "Tracktion source patch is missing or changed. Run python scripts/dev.py bootstrap. ${ENGINE_PATCH_ERROR}")
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
    add_subdirectory("${ENGINE_ROOT}/modules" "dependencies/tracktion")
    juce_add_gui_app(EMusician PRODUCT_NAME "E-musician" COMPANY_NAME "E-musician"
        BUNDLE_ID "local.emusician.desktop")
    if(WIN32)
        # JUCE 8.0.6 omits its Info.txt dependency for generated Windows resources.
        # Keep Explorer's file/product version current on incremental builds.
        get_target_property(EMUSICIAN_GENERATED_DIR EMusician JUCE_GENERATED_SOURCES_DIRECTORY)
        get_target_property(EMUSICIAN_INFO_FILE EMusician JUCE_INFO_FILE)
        add_custom_command(OUTPUT "${EMUSICIAN_GENERATED_DIR}/EMusician_resources.rc"
            APPEND DEPENDS "${EMUSICIAN_INFO_FILE}")
    endif()
    target_sources(EMusician PRIVATE apps/desktop/Main.cpp apps/desktop/EngineSession.cpp
        apps/desktop/MainComponent.cpp apps/desktop/ArrangementView.cpp
        apps/desktop/ProjectStorage.cpp apps/desktop/AudioSource.cpp apps/desktop/PluginHost.cpp
        apps/desktop/PianoRoll.cpp apps/desktop/ControlServer.cpp apps/desktop/SelectedTrackPanel.cpp tests/Vst3InactiveBusSmoke.cpp)
    # Keep the application-reported version and window title tied to the build version.
    set_property(SOURCE apps/desktop/Main.cpp APPEND PROPERTY COMPILE_DEFINITIONS
        "EMUSICIAN_APPLICATION_VERSION=\"${PROJECT_VERSION}\"")
    target_include_directories(EMusician PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}" "${CMAKE_CURRENT_SOURCE_DIR}/_deps/asio_sdk/common")
    target_compile_definitions(EMusician PRIVATE JUCE_WEB_BROWSER=0 JUCE_USE_CURL=0 JUCE_USE_MP3AUDIOFORMAT=1
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
    set_target_properties(EMusician PROPERTIES OUTPUT_NAME "E-musician"
        RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin/$<CONFIG>")
    add_test(NAME engine.integration_smoke COMMAND "${Python3_EXECUTABLE}"
        "${CMAKE_CURRENT_SOURCE_DIR}/tests/RunEngineSmoke.py"
        "$<TARGET_FILE:EMusician>" "${CMAKE_BINARY_DIR}/smoke/$<CONFIG>")
    set_tests_properties(engine.integration_smoke PROPERTIES TIMEOUT 260 RUN_SERIAL TRUE)
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
