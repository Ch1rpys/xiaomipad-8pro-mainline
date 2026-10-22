// SPDX-License-Identifier: MIT
#include "panel.hpp"
#include <fstream>
#include <stdexcept>
#include <system_error>

namespace nvt {
namespace {
constexpr int kCsotProjectVendorId = 4;
constexpr int kBoeProjectVendorId = 26;

int projectVendorId(PanelVendor vendor) {
    return vendor == PanelVendor::Boe ? kBoeProjectVendorId : kCsotProjectVendorId;
}
}

PanelIdentity readPanelVendor(const std::filesystem::path &node, const std::filesystem::path &sysfs) {
    std::error_code error;
    const auto resolved = std::filesystem::canonical(node, error);
    const auto name = (error ? node : resolved).filename();
    std::ifstream stream(sysfs / "class/misc" / name / "device/panel_vendor");
    if (!stream)
        return {};
    std::string value;
    std::getline(stream, value);
    if (value == "csot")
        return {PanelVendor::Csot, true};
    if (value == "boe")
        return {PanelVendor::Boe, true};
    throw std::runtime_error("unsupported kernel panel_vendor '" + value + "'");
}

const char *panelVendorName(PanelVendor vendor) {
    return vendor == PanelVendor::Boe ? "boe" : "csot";
}

std::optional<std::string> calibrationMismatch(PanelVendor vendor, std::optional<int> project_vendor_id) {
    if (!project_vendor_id || *project_vendor_id == projectVendorId(vendor))
        return std::nullopt;
    const auto other = vendor == PanelVendor::Boe ? PanelVendor::Csot : PanelVendor::Boe;
    std::string source = *project_vendor_id == projectVendorId(other)
                             ? std::string("the ") + panelVendorName(other) + " panel"
                             : "no piano panel";
    return "touch calibration has project_vendor_id " + std::to_string(*project_vendor_id) + " (" + source +
           ") but the kernel reports a " + panelVendorName(vendor) + " panel; extract it from piano_nova_" +
           panelVendorName(vendor) + "_thp_config.ini";
}
} // namespace nvt
