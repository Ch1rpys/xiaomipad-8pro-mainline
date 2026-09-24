// SPDX-License-Identifier: MIT
// Run explicitly in a disposable Linux guest: creates a synthetic input device.
#include "input.hpp"
#include <algorithm>
#include <array>
#include <filesystem>
#include <fcntl.h>
#include <iostream>
#include <limits>
#include <optional>
#include <poll.h>
#include <set>
#include <stdexcept>
#include <sys/ioctl.h>
#include <unistd.h>

namespace {
void check(bool result, const char *message) {
    if (!result)
        throw std::runtime_error(message);
}

std::array<int, nvt::kFingerSlots> slots(int fd, unsigned axis) {
    std::array<int, nvt::kFingerSlots + 1> values{};
    values[0] = axis;
    check(ioctl(fd, EVIOCGMTSLOTS(sizeof(values)), values.data()) >= 0, "EVIOCGMTSLOTS failed");
    std::array<int, nvt::kFingerSlots> result{};
    std::copy(values.begin() + 1, values.end(), result.begin());
    return result;
}

bool touched(int fd) {
    std::array<uint8_t, (KEY_MAX + 8) / 8> keys{};
    check(ioctl(fd, EVIOCGKEY(keys.size()), keys.data()) >= 0, "EVIOCGKEY failed");
    return keys[BTN_TOUCH / 8] & (1 << (BTN_TOUCH % 8));
}

int openEvent(const std::string &sysname) {
    for (const auto &entry : std::filesystem::directory_iterator("/sys/class/input/" + sysname)) {
        const auto name = entry.path().filename().string();
        if (name.starts_with("event")) {
            const int fd = open(("/dev/input/" + name).c_str(), O_RDONLY | O_NONBLOCK | O_CLOEXEC);
            check(fd >= 0, "cannot open newly created evdev node");
            return fd;
        }
    }
    throw std::runtime_error("uinput device has no evdev handler");
}
} // namespace

int main(int argc, char **argv) {
    if (argc != 2 || std::string_view(argv[1]) != "--create-test-device") {
        std::cerr << "Usage: test-uinput --create-test-device\n"
                  << "Creates synthetic input; use a disposable guest, not a desktop session.\n";
        return 2;
    }
    int fd = -1;
    try {
        std::optional<nvt::UInputTouch> input;
        input.emplace(32000, 21360);
        fd = openEvent(input->sysname());
        input_absinfo x{}, y{}, count{};
        check(ioctl(fd, EVIOCGABS(ABS_MT_POSITION_X), &x) == 0 && x.maximum == 31999,
              "X axis does not match supplied dimensions");
        check(ioctl(fd, EVIOCGABS(ABS_MT_POSITION_Y), &y) == 0 && y.maximum == 21359,
              "Y axis does not match supplied dimensions");
        check(ioctl(fd, EVIOCGABS(ABS_MT_SLOT), &count) == 0 && count.maximum == nvt::kFingerSlots - 1,
              "wrong MT slot count");
        std::array<uint8_t, (INPUT_PROP_MAX + 8) / 8> properties{};
        check(ioctl(fd, EVIOCGPROP(properties.size()), properties.data()) >= 0 &&
              (properties[INPUT_PROP_DIRECT / 8] & (1 << (INPUT_PROP_DIRECT % 8))),
              "input device is not direct touch");
        std::array<nvt::Slot, nvt::kFingerSlots> contacts{};
        for (int index = 0; index < nvt::kFingerSlots; ++index) {
            contacts[index].number = index;
            contacts[index].tracking_id = index + 100000;
            contacts[index].contact.x = 1000 + index * 100;
            contacts[index].contact.y = 2000 + index * 100;
            contacts[index].contact.area = index;
        }
        input->report(contacts);
        const auto identifiers = slots(fd, ABS_MT_TRACKING_ID);
        check(std::set<int>(identifiers.begin(), identifiers.end()).size() == nvt::kFingerSlots,
              "initial tracking IDs collide");
        check(touched(fd), "BTN_TOUCH not set");
        const auto initial_x = slots(fd, ABS_MT_POSITION_X), initial_y = slots(fd, ABS_MT_POSITION_Y);
        for (int index = 0; index < nvt::kFingerSlots; ++index) {
            check(identifiers[index] >= 0 && identifiers[index] <= 65535, "tracking ID outside range");
            check(initial_x[index] == contacts[index].contact.x && initial_y[index] == contacts[index].contact.y,
                  "multitouch coordinates changed or were lost");
        }
        std::array<input_event, 256> events{};
        const auto bytes = read(fd, events.data(), sizeof(events));
        check(bytes > 0 && bytes % sizeof(input_event) == 0, "evdev did not deliver whole events");
        check(std::any_of(events.begin(), events.begin() + bytes / sizeof(input_event), [](const auto &event) {
            return event.type == EV_SYN && event.code == SYN_REPORT;
        }), "no SYN_REPORT reached evdev");
        std::cout << "PASS: all " << nvt::kFingerSlots << " slots reached real uinput/input/evdev unchanged\n";

        input->report(std::span(contacts).first(2));
        auto ids = slots(fd, ABS_MT_TRACKING_ID);
        check(ids[0] == identifiers[0] && ids[1] == identifiers[1] &&
              std::all_of(ids.begin() + 2, ids.end(), [](int id) { return id == -1; }),
              "partial release or stable IDs failed");
        contacts[0].contact.x = -1;
        contacts[0].contact.y = std::numeric_limits<int>::max();
        input->report(std::span(contacts).first(2));
        check(slots(fd, ABS_MT_POSITION_X)[0] == 0 && slots(fd, ABS_MT_POSITION_Y)[0] == 21359,
              "out-of-range coordinates were not bounded");
        for (int index = 0; index < 65536; ++index) {
            contacts[1].tracking_id = 100001 + index;
            input->report(std::span(contacts).first(2));
        }
        ids = slots(fd, ABS_MT_TRACKING_ID);
        check(ids[0] == identifiers[0] && ids[1] != ids[0] && ids[1] >= 0 && ids[1] <= 65535,
              "tracking ID wrap collided with a held contact");
        input->report({});
        ids = slots(fd, ABS_MT_TRACKING_ID);
        check(!touched(fd) && std::all_of(ids.begin(), ids.end(), [](int id) { return id == -1; }),
              "release did not clear kernel input state");
        std::cout << "PASS: partial release, coordinate bounds, 16-bit ID wrap and full release\n";

        input->report(std::span(contacts).first(1));
        input.reset();
        pollfd watch{fd, POLLIN, 0};
        check(poll(&watch, 1, 0) >= 0 && (watch.revents & POLLHUP), "destroyed device did not hang up evdev");
        close(fd);
        std::cout << "PASS: destruction removes input device; no physical touch tested\n";
        return 0;
    } catch (const std::exception &error) {
        if (fd >= 0)
            close(fd);
        std::cerr << error.what() << '\n';
        return 1;
    }
}
