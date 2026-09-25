// SPDX-License-Identifier: MIT
#pragma once
#include "nvt_touch_core.hpp"
#include <algorithm>
#include <span>
#include <vector>

namespace nvt {
// Piano panel orientation, taken from the P15 device session: the operator tapped
// top-left, top-right, bottom-right, bottom-left (landscape, USB port on the right,
// on the keyboard) and confirmed that order. The recorded processor coordinates were
// (X low, Y high), (X low, Y low), (X high, Y low), (X high, Y high): processor X
// (electrode columns) runs top to bottom and processor Y (rows) runs right to left.
// The panel therefore reports X = reversed processor Y along the 3200-pixel side and
// Y = processor X along the 2136-pixel side. A wrong mapping is corrected here only.
struct PanelAxes {
    int width;
    int height;
};

inline PanelAxes panelAxes(const Calibration &calibration) {
    return {calibration.row_maximum, calibration.column_maximum};
}

inline Contact panelContact(Contact contact, const Calibration &calibration) {
    const int x = std::clamp(contact.x, 0, calibration.column_maximum - 1);
    const int y = std::clamp(contact.y, 0, calibration.row_maximum - 1);
    contact.x = calibration.row_maximum - 1 - y;
    contact.y = x;
    return contact;
}

inline void panelSlots(std::span<const Slot> slots, const Calibration &calibration,
                       std::vector<Slot> &output) {
    output.assign(slots.begin(), slots.end());
    for (Slot &slot : output)
        slot.contact = panelContact(slot.contact, calibration);
}
} // namespace nvt
