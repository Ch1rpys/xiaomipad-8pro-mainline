// SPDX-License-Identifier: MIT
#pragma once

#include "nvt_touch_core.hpp"
#include <span>

namespace nvt {

struct FingerFrame {
    uint16_t counter;
    uint8_t scan_mode;
    Matrix matrix;
};

// Validate the firmware-defined checksum region; trailing transport padding is retained by the caller.
FingerFrame parseFingerFrame(std::span<const uint8_t> payload);

} // namespace nvt
