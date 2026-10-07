// SPDX-License-Identifier: MIT
// Synthetic protocol/lifecycle tests are not evidence of physical finger tracking.
#include "calibration.hpp"
#include "live_pipeline.hpp"
#include "orientation.hpp"
#include <algorithm>
#include <fstream>
#include <iostream>
#include <stdexcept>

namespace {
void check(bool result, const char *message) {
    if (!result)
        throw std::runtime_error(message);
}

template<typename Function> void rejects(Function call, const char *message) {
    try { call(); } catch (const std::runtime_error &) { return; }
    throw std::runtime_error(message);
}

void put(std::span<uint8_t> data, size_t offset, uint64_t value, size_t length) {
    for (size_t index = 0; index < length; ++index)
        data[offset + index] = value >> (index * 8);
}

uint64_t get(std::span<const uint8_t> data, size_t offset, size_t length) {
    uint64_t value = 0;
    for (size_t index = 0; index < length; ++index)
        value |= uint64_t{data[offset + index]} << (index * 8);
    return value;
}

std::vector<uint8_t> wire(std::span<const uint8_t> payload, uint64_t sequence,
                          uint64_t timestamp, uint16_t flags) {
    std::vector<uint8_t> data(32 + 257 + payload.size());
    put(data, 0, 0x3150544e, 4);
    put(data, 4, 32, 2);
    put(data, 6, 257 + payload.size(), 2);
    put(data, 8, sequence, 8);
    put(data, 16, timestamp, 8);
    put(data, 24, get(payload, 4, 2), 2);
    put(data, 26, flags, 2);
    put(data, 28, get(payload, 8, 4), 4);
    std::copy(payload.begin(), payload.end(), data.begin() + 32 + 257);
    return data;
}

void checksum(std::span<uint8_t> payload) {
    uint32_t sum = 0;
    for (size_t offset = 20; offset < 20 + get(payload, 8, 4) * 4; offset += 2)
        sum += get(payload, offset, 2);
    const uint16_t crc = uint16_t(-sum);
    put(payload, 4, crc, 2);
    put(payload, 12, uint16_t(~crc), 2);
}

std::vector<uint8_t> packet(uint16_t counter, bool touch = false, uint8_t type = 3,
                            uint8_t scan = 4) {
    std::vector<uint8_t> payload(5192);
    payload[0] = 0xa5;
    put(payload, 2, counter, 2);
    put(payload, 8, 0x4c3, 4);
    put(payload, 16, uint32_t(~0x4c3), 4);
    payload[24] = scan;
    payload[48] = nvt::kColumns;
    payload[49] = nvt::kRows;
    payload[56] = type;
    for (int row = 0; row < nvt::kRows; ++row) {
        for (int column = 0; column < nvt::kColumns; ++column) {
            int value = 10000;
            const int x = column - 30, y = row - 20;
            if (touch && std::abs(x) <= 1 && std::abs(y) <= 1)
                value += !x && !y ? 1000 : (!x || !y ? 500 : 250);
            put(payload, 64 + 2 * (row * nvt::kColumns + column), value, 2);
        }
    }
    checksum(payload);
    return payload;
}

nvt::Calibration calibration() {
    nvt::Calibration value{};
    for (int row = 0; row < nvt::kRows; ++row)
        value.row_map[row] = (row + 1) * 10;
    for (int column = 0; column < nvt::kColumns; ++column)
        value.column_map[column] = (column + 1) * 10;
    value.row_maximum = 4100;
    value.column_maximum = 6100;
    value.edge_size = 100;
    value.edge_base = value.edge_gain = 1000;
    return value;
}

struct Fixture {
    std::vector<nvt::Slot> visible;
    size_t reports = 0;
    nvt::LivePipeline pipeline{calibration(), [&](auto slots) {
        visible.assign(slots.begin(), slots.end());
        ++reports;
    }};
    nvt::StreamReader reader;
    uint64_t sequence = 0, timestamp = 1000000000;

    void feed(std::span<const uint8_t> payload, uint16_t flags = nvt::kStreamValid,
              size_t chunk = 127) {
        ++sequence;
        timestamp += 8333333;
        const auto bytes = wire(payload, sequence, timestamp, flags);
        for (size_t offset = 0; offset < bytes.size(); offset += chunk)
            reader.feed(std::span(bytes).subspan(offset, std::min(chunk, bytes.size() - offset)),
                        [&](const auto &record) { pipeline.feed(record, record.timestamp_ns); });
    }

    void activate() {
        feed(packet(0, false, 3, 2), nvt::kStreamValid | nvt::kStreamEpoch);
        for (uint16_t index = 1; index <= 4; ++index)
            feed(packet(index, true));
        check(visible.size() == 1, "synthetic pipeline did not activate a slot");
        check(visible[0].contact.x == 3100 && visible[0].contact.y == 2100,
              "synthetic processor axes were transformed unexpectedly");
    }
};

void framing() {
    const auto payload = packet(42);
    const auto bytes = wire(payload, 19, 1000000000, nvt::kStreamValid);
    for (const size_t chunk : {size_t{1}, size_t{31}, size_t{32}, size_t{257}, bytes.size()}) {
        nvt::StreamReader reader;
        unsigned int calls = 0;
        auto consume = [&](const nvt::StreamRecord &record) {
            ++calls;
            check(record.sequence == 19 && record.timestamp_ns == 1000000000,
                  "NTP1 endian/sequence mismatch");
            check(std::equal(record.payload.begin(), record.payload.end(), payload.begin(), payload.end()),
                  "NTP1 payload differs");
        };
        for (unsigned int repeat = 0; repeat < 2; ++repeat)
            for (size_t offset = 0; offset < bytes.size(); offset += chunk)
                reader.feed(std::span(bytes).subspan(offset, std::min(chunk, bytes.size() - offset)), consume);
        reader.finish();
        check(calls == 2, "split/concatenated record count mismatch");
    }
    for (const size_t length : {size_t{1}, size_t{31}, size_t{32}, bytes.size() - 1}) {
        nvt::StreamReader reader;
        reader.feed(std::span(bytes).first(length), [](auto &) {});
        rejects([&] { reader.finish(); }, "truncated stream accepted");
    }
    for (const auto &[offset, value] : std::array<std::pair<size_t, uint8_t>, 5>{
            {{0, 0}, {4, 31}, {6, 0}, {7, 0xff}, {26, 0x80}}}) {
        auto bad = bytes;
        bad[offset] = value;
        if (offset == 6)
            bad[7] = 0;
        nvt::StreamReader reader;
        rejects([&] { reader.feed(bad, [](auto &) {}); }, "bad stream header accepted");
    }
}

void lifecycle() {
    Fixture f;
    f.activate();
    f.pipeline.expire(f.timestamp + nvt::LivePipeline::kStallNs - 1);
    check(!f.visible.empty(), "released before stall deadline");
    f.pipeline.expire(f.timestamp + nvt::LivePipeline::kStallNs);
    check(f.visible.empty() && f.pipeline.stats.stalls == 1, "stall did not release touch");
    f.activate();
    f.feed(packet(5, false, 29));
    check(f.pipeline.stats.other_types == 1 && !f.visible.empty(), "pen packet was treated as a finger");
    f.timestamp += nvt::LivePipeline::kStallNs;
    f.feed(packet(6, false, 29));
    check(f.visible.empty(), "pen traffic kept stale finger alive");
    f.activate();
    f.feed(packet(7), 0);
    check(f.visible.empty() && f.pipeline.stats.invalid == 1, "invalid flag did not release touch");
    f.activate();
    auto bad = packet(8);
    bad[64] ^= 1;
    f.feed(bad);
    check(f.visible.empty() && f.pipeline.stats.invalid == 2, "bad checksum did not release touch");
    f.activate();
    ++f.sequence;
    f.feed(packet(9, true));
    check(f.visible.empty(), "sequence gap did not release touch");
    f.activate();
    --f.sequence;
    f.feed(packet(10, true));
    check(f.visible.empty() && f.pipeline.stats.invalid == 3, "duplicate sequence accepted");
    f.activate();
    f.timestamp -= 10000000;
    f.feed(packet(11, true));
    check(f.visible.empty() && f.pipeline.stats.invalid == 4, "reversed time accepted");
    f.activate();
    f.feed(packet(12, false, 3, 2), nvt::kStreamValid | nvt::kStreamEpoch);
    check(f.visible.empty(), "new firmware epoch retained a contact");
    f.activate();
    const auto stale = wire(packet(13, true), ++f.sequence, f.timestamp + 8333333, nvt::kStreamValid);
    f.reader.feed(stale, [&](const auto &record) {
        f.pipeline.feed(record, record.timestamp_ns + nvt::LivePipeline::kStallNs);
    });
    check(f.visible.empty() && f.pipeline.stats.stale == 1, "queued stale contact was replayed");
    f.timestamp += 8333333;
    f.activate();
    const auto future = wire(packet(14, true), ++f.sequence, f.timestamp + 8333333, nvt::kStreamValid);
    f.reader.feed(future, [&](const auto &record) {
        f.pipeline.feed(record, record.timestamp_ns - 1);
    });
    check(f.visible.empty() && f.pipeline.stats.stale == 2, "future timestamp was accepted");
    f.reader.finish();
}

void orientation() {
    auto value = calibration();
    value.column_maximum = 32000;
    value.row_maximum = 21360;
    const auto axes = nvt::panelAxes(value);
    check(axes.width == 32000 && axes.height == 21360, "panel ranges do not follow the panel axes");
    // Processor coordinates of the P15 corner taps in recorded order. The 2026-10-07
    // swipes place them at top-left, bottom-left, bottom-right and top-right; the
    // 2026-09-25 confirmed clockwise order did not match the recorded taps.
    constexpr std::array<std::array<int, 4>, 5> corners{{
        {520, 21291, 520, 68}, {1603, 661, 1603, 20698}, {31412, 384, 31412, 20975},
        {31198, 20866, 31198, 493}, {-5, 40000, 0, 0}}};
    std::vector<nvt::Slot> slots(corners.size()), panel;
    for (size_t index = 0; index < corners.size(); ++index) {
        slots[index].number = int(index);
        slots[index].contact.x = corners[index][0];
        slots[index].contact.y = corners[index][1];
    }
    nvt::panelSlots(slots, value, panel);
    for (size_t index = 0; index < corners.size(); ++index)
        check(panel[index].number == int(index) && panel[index].contact.x == corners[index][2] &&
              panel[index].contact.y == corners[index][3], "P15 corner mapped to the wrong panel position");
    const auto &tl = panel[0].contact, &bl = panel[1].contact, &br = panel[2].contact, &tr = panel[3].contact;
    check(tl.x < tr.x && bl.x < br.x && tl.y < bl.y && tr.y < br.y, "panel corners are not upright");

    const auto at = [&](int x, int y) {
        nvt::Contact contact;
        contact.x = x;
        contact.y = y;
        return nvt::panelContact(contact, value);
    };
    // Left-to-right swipe: constant processor row, increasing processor column.
    nvt::Contact previous;
    for (int column : {141, 9000, 18000, 27795}) {
        const auto point = at(column, 12000);
        check(point.y == 21359 - 12000 && (column == 141 || point.x > previous.x),
              "left-to-right swipe does not increase X at constant Y");
        previous = point;
    }
    // Top-to-bottom swipe: constant processor column, processor row falling from the top edge.
    for (int row : {21108, 14000, 7000, 37}) {
        const auto point = at(16000, row);
        check(point.x == 16000 && (row == 21108 || point.y > previous.y),
              "top-to-bottom swipe does not increase Y at constant X");
        previous = point;
    }
    // P18 swipe endpoints as emitted by the ccb78ad transform (X, Y) become (Y, X) now.
    constexpr std::array<std::array<int, 2>, 4> emitted{{{8813, 141}, {9442, 27795}, {251, 16057}, {21322, 15722}}};
    for (const auto &old : emitted) {
        const auto point = at(old[1], 21359 - old[0]);
        check(point.x == old[1] && point.y == old[0], "P18 swipe endpoint is not the transposed output");
    }
}

void stock(const char *configuration, const char *path) {
    struct Record { uint64_t sequence, timestamp; std::array<uint8_t, 5192> payload; };
    std::vector<Record> records;
    std::array<uint8_t, 5216> data{};
    std::ifstream file(path, std::ios::binary);
    check(bool(file), "cannot open stock fixture");
    while (file.read(reinterpret_cast<char *>(data.data()), data.size())) {
        Record record{get(data, 8, 8), get(data, 0, 8), {}};
        std::copy(data.begin() + 24, data.end(), record.payload.begin());
        records.push_back(record);
    }
    check(file.eof() && !file.gcount() && records.size() == 10, "expected ten complete stock slots");
    std::sort(records.begin(), records.end(), [](const auto &a, const auto &b) { return a.sequence < b.sequence; });
    size_t contacts = 0;
    nvt::LivePipeline pipeline(nvt::loadCalibration(configuration), [&](auto slots) { contacts += slots.size(); });
    nvt::StreamReader reader;
    for (size_t index = 0; index < records.size(); ++index) {
        const auto &record = records[index];
        // Envelope and time conversion are synthetic; the actual payload bytes stay unchanged.
        const auto bytes = wire(record.payload, record.sequence,
                                record.timestamp - records[0].timestamp + 1000000000,
                                nvt::kStreamValid | (index == 0 ? nvt::kStreamEpoch : 0));
        for (size_t offset = 0; offset < bytes.size(); offset += 17)
            reader.feed(std::span(bytes).subspan(offset, std::min(size_t{17}, bytes.size() - offset)),
                        [&](const auto &value) { pipeline.feed(value, value.timestamp_ns); });
    }
    reader.finish();
    const auto &s = pipeline.stats;
    check(s.records == 10 && s.fingers == 10 && !s.invalid && s.baselines == 1 &&
          s.processed == 1 && !contacts, "actual idle payload replay differs from stock-ring replay");
    std::cout << "PASS: 10 actual idle payloads in synthetic NTP1 envelopes, one processed, zero contacts\n";
}
} // namespace

int main(int argc, char **argv) {
    try {
        if (argc != 1 && argc != 3)
            throw std::runtime_error("Usage: test-live [CALIBRATION.json STOCK_RECORDS.bin]");
        framing();
        lifecycle();
        orientation();
        std::cout << "PASS: synthetic NTP1 splits/bounds, contact release lifecycle, P15 corner and "
                     "P18 swipe orientation; not hardware evidence\n";
        if (argc == 3)
            stock(argv[1], argv[2]);
        return 0;
    } catch (const std::exception &error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
