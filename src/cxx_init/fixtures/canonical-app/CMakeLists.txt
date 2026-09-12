cmake_minimum_required(VERSION 3.25)

project(robot_runtime LANGUAGES CXX)

option(ENABLE_SANITIZERS "Enable address and undefined behavior sanitizers" OFF)

include(CTest)

add_executable(robot_runtime src/main.cpp)
target_compile_features(robot_runtime PRIVATE cxx_std_23)
set_target_properties(robot_runtime PROPERTIES CXX_EXTENSIONS OFF)

if(MSVC)
    target_compile_options(robot_runtime PRIVATE /W4 /permissive-)
elseif(CMAKE_CXX_COMPILER_ID MATCHES "^(AppleClang|Clang|GNU)$")
    target_compile_options(robot_runtime PRIVATE -Wall -Wextra -Wpedantic)
endif()

if(ENABLE_SANITIZERS)
    if(CMAKE_CXX_COMPILER_ID MATCHES "^(AppleClang|Clang|GNU)$")
        # Undefined behavior must fail the run, not merely emit a diagnostic.
        target_compile_options(
            robot_runtime PRIVATE -fsanitize=address,undefined -fno-omit-frame-pointer
            -fno-sanitize-recover=undefined
        )
        target_link_options(robot_runtime PRIVATE -fsanitize=address,undefined)
    else()
        message(FATAL_ERROR "Sanitizers are only configured for Clang, AppleClang, and GCC")
    endif()
endif()

if(BUILD_TESTING)
    # Exercise the actual app; a nonzero exit or timeout is a test failure.
    add_test(NAME robot_runtime.smoke COMMAND robot_runtime)
    set_tests_properties(robot_runtime.smoke PROPERTIES TIMEOUT 10)
endif()
