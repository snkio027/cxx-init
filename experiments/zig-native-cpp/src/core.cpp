#include "core.hpp"
#include "private.hpp"
#include "config.hpp"
#include <toml++/toml.hpp>

int probe::answer() {
    auto table = toml::parse("value = 36");
    return table["value"].value_or(0) + private_offset + public_offset + PROBE_BIAS;
}
