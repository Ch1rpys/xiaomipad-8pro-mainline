// SPDX-License-Identifier: MIT
#include "calibration.hpp"
#include "processor.hpp"
#include <algorithm>
#include <array>
#include <fstream>
#include <iostream>
#include <nlohmann/json.hpp>
#include <stdexcept>

namespace {
constexpr size_t kStockRecordSize = 5216;
constexpr size_t kStockPayloadOffset = 24;

uint64_t le64(const uint8_t *data) {
    uint64_t value = 0;
    for (unsigned int index = 0; index < 8; ++index)
        value |= uint64_t{data[index]} << (index * 8);
    return value;
}

struct Record {
    uint64_t timestamp_ns;
    uint64_t sequence;
    nvt::FingerFrame frame;
};
}

int main(int argc, char **argv) {
    if (argc != 4 || std::string_view(argv[1]) != "--stock-ring") {
        std::cerr << "Usage: piano-thp-replay --stock-ring CALIBRATION.json RECORDS.bin\n"
                  << "Offline replay only; no input device, firmware command or tablet access.\n";
        return 2;
    }
    try {
        const auto calibration = nvt::loadCalibration(argv[2]);
        nvt::FingerProcessor processor(calibration);
        std::ifstream input(argv[3], std::ios::binary);
        if (!input)
            throw std::runtime_error("cannot open stock records");
        std::vector<Record> records;
        std::array<uint8_t, kStockRecordSize> raw{};
        while (input.read(reinterpret_cast<char *>(raw.data()), raw.size())) {
            const auto timestamp = le64(raw.data());
            if (timestamp == 0 || timestamp > uint64_t{INT64_MAX})
                throw std::runtime_error("invalid stock realtime timestamp");
            records.push_back({timestamp, le64(raw.data() + 8),
                nvt::parseFingerFrame(std::span(raw).subspan(kStockPayloadOffset))});
        }
        if (!input.eof() || input.gcount() != 0 || records.empty())
            throw std::runtime_error("empty or truncated stock record input");
        std::sort(records.begin(), records.end(), [](const auto &a, const auto &b) {
            return a.sequence < b.sequence;
        });
        size_t processed = 0, baselines = 0, contacts = 0;
        for (size_t index = 0; index < records.size(); ++index) {
            const auto &record = records[index];
            if (index && (record.sequence == records[index - 1].sequence ||
                          record.timestamp_ns <= records[index - 1].timestamp_ns))
                throw std::runtime_error("duplicate sequence or non-monotonic stock time");
            const auto update = processor.feed(record.frame, record.timestamp_ns);
            nlohmann::json event{{"sequence", record.sequence}, {"timestamp_ns", record.timestamp_ns},
                                {"scan_mode", record.frame.scan_mode}, {"baseline_ready", update.baseline_ready},
                                {"slots", nlohmann::json::array()}};
            if (update.baseline_ready)
                ++baselines;
            if (update.result) {
                ++processed;
                for (const auto &slot : update.result->slots) {
                    event["slots"].push_back({{"slot", slot.number}, {"tracking_id", slot.tracking_id},
                        {"x", slot.contact.x}, {"y", slot.contact.y}});
                    ++contacts;
                }
            }
            std::cout << event.dump() << '\n';
        }
        std::cerr << nlohmann::json{{"records", records.size()}, {"baseline_events", baselines},
            {"processed_frames", processed}, {"reported_slots", contacts},
            {"scope", "Offline stock-ring replay; not hardware input or coordinate calibration validation"}}.dump() << '\n';
        return 0;
    } catch (const std::exception &error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
