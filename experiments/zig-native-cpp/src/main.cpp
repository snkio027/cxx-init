#include "core.hpp"
#include <cstdlib>
#include <print>

int main(int argc, char** argv) {
    const int actual = probe::answer();
    std::println("answer={}", actual);
    return argc > 1 && actual != std::atoi(argv[1]) ? 23 : 0;
}
