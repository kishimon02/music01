cmake_minimum_required(VERSION 3.22)
project(music_create_native LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

add_library(audio_core SHARED
  audio_core/src/audio_core.cpp
)
target_include_directories(audio_core PUBLIC audio_core/include)

if (WIN32)
  target_link_libraries(audio_core PRIVATE winmm)
endif()

# Placeholder for future pybind11 module.
# add_subdirectory(bindings)
