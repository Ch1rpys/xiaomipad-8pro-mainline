// SPDX-License-Identifier: MIT
// Synthetic coordinate-regression fixtures only, never hardware touch evidence.
#include "processor.hpp"
#include <iostream>
#include <stdexcept>

namespace {
void check(bool condition, const char *message) {
    if (!condition)
        throw std::runtime_error(message);
}

nvt::Calibration calibration(int row_shift, int column_shift) {
    nvt::Calibration value{};
    for (int row = 0; row < nvt::kRows; ++row)
        value.row_map[row] = 10 * (row + 1) + row_shift;
    for (int column = 0; column < nvt::kColumns; ++column)
        value.column_map[column] = 10 * (column + 1) + column_shift;
    value.row_maximum = 10 * (10 * (nvt::kRows + 1) + row_shift);
    value.column_maximum = 10 * (10 * (nvt::kColumns + 1) + column_shift);
    value.edge_size = 100;
    value.edge_base = 1000;
    value.edge_gain = 1000;
    return value;
}

void exercise(const nvt::Calibration &value) {
    nvt::FingerProcessor processor(value);
    nvt::FingerFrame frame{0, 2, {}};
    frame.matrix.fill(10000);
    check(processor.feed(frame, 1000000000).baseline_ready, "reference not accepted");
    constexpr int row = 20, column = 30;
    for (int y = -1; y <= 1; ++y)
        for (int x = -1; x <= 1; ++x)
            frame.matrix[(row + y) * nvt::kColumns + column + x] +=
                x == 0 && y == 0 ? 1000 : (x == 0 || y == 0 ? 500 : 250);
    frame.scan_mode = 4;
    nvt::FingerProcessor::Update update;
    for (int index = 1; index <= 4; ++index) {
        frame.counter = index;
        update = processor.feed(frame, 1000000000 + index * 8333333);
    }
    check(update.result.has_value() && update.result->slots.size() == 1, "expected one synthetic contact");
    const auto &contact = update.result->slots[0].contact;
    check(contact.x == value.column_map[column] * nvt::kSuperResolution, "column calibration not used");
    check(contact.y == value.row_map[row] * nvt::kSuperResolution, "row calibration not used");
    processor.reset();
    frame.scan_mode = 2;
    frame.matrix.fill(10000);
    check(processor.feed(frame, 2000000000).baseline_ready, "epoch reset failed");
}
}

int main() {
    try {
        exercise(calibration(0, 0));
        exercise(calibration(13, 27));
        auto invalid = calibration(0, 0);
        invalid.row_map[1] = invalid.row_map[0];
        bool rejected = false;
        try { invalid.validate(); } catch (const std::invalid_argument &) { rejected = true; }
        check(rejected, "non-increasing map accepted");
        std::cout << "PASS: two synthetic calibrations, reset, invalid-map rejection; not a hardware test\n";
        return 0;
    } catch (const std::exception &error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
