# SPDX-License-Identifier: MIT
CXX ?= g++
OUT ?= build
CPPFLAGS += -Isrc $(if $(JSON_INCLUDE),-I$(JSON_INCLUDE))
CXXFLAGS ?= -O2 -std=c++20
CXXFLAGS += -Wall -Wextra -Werror -MMD -MP
SOURCES := nvt_touch_core nvt_finger_filter frame processor calibration replay
OBJECTS := $(addprefix $(OUT)/,$(addsuffix .o,$(SOURCES)))

.PHONY: all test
all: $(OUT)/piano-thp-replay

$(OUT):
	mkdir -p "$@"

$(OUT)/%.o: src/%.cpp | $(OUT)
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) -c $< -o $@

$(OUT)/piano-thp-replay: $(OBJECTS)
	$(CXX) $(LDFLAGS) $^ $(LDLIBS) -o $@

$(OUT)/test-calibration: tests/calibration.cpp $(filter-out $(OUT)/replay.o $(OUT)/calibration.o,$(OBJECTS))
	$(CXX) $(CPPFLAGS) $(CXXFLAGS) $(LDFLAGS) $^ $(LDLIBS) -o $@

test: $(OUT)/test-calibration
	$(RUNNER) $(OUT)/test-calibration

-include $(OBJECTS:.o=.d)
