#include "core/commands/RevisionGuard.hpp"
#include "core/time/Time.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <exception>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <string_view>

namespace {

class Checks {
public:
    void expect(bool condition, std::string_view label)
    {
        ++total_;
        if (!condition) {
            ++failed_;
            std::cerr << "FAIL: " << label << '\n';
        }
    }

    void near(double actual, double expected, std::string_view label)
    {
        const double scale = std::max({1.0, std::abs(actual), std::abs(expected)});
        expect(std::isfinite(actual) && std::abs(actual - expected) <= 1e-12 * scale, label);
    }

    template <typename Exception, typename Function>
    void throws(Function&& operation, std::string_view label)
    {
        bool matched = false;
        try {
            operation();
        } catch (const Exception&) {
            matched = true;
        } catch (const std::exception& exception) {
            std::cerr << "Unexpected exception for " << label << ": " << exception.what() << '\n';
        } catch (...) {
            std::cerr << "Unexpected non-standard exception for " << label << '\n';
        }
        expect(matched, label);
    }

    [[nodiscard]] int finish() const
    {
        std::cout << "Core checks: " << total_ - failed_ << '/' << total_ << " passed\n";
        return failed_ == 0 ? 0 : 1;
    }

private:
    int total_ = 0;
    int failed_ = 0;
};

void testTime(Checks& checks)
{
    using namespace emusician::time;
    checks.near(beatsToSeconds(32.0, 112.0), 120.0 / 7.0,
                "eight 4/4 bars at 112 BPM have the expected duration");
    checks.near(secondsToBeats(30.0, 120.0), 60.0, "seconds convert to beat positions");

    for (const double bpm : {20.0, 60.0, 112.0, 300.0}) {
        for (const double seconds : {0.0, 0.5, 17.142857142857, 3600.25}) {
            checks.near(beatsToSeconds(secondsToBeats(seconds, bpm), bpm), seconds,
                        "seconds/beat roundtrip across tempos and durations");
        }
    }

    checks.expect(secondsToSamples(1.0, 44100.0) == 44100, "one second at 44.1 kHz");
    checks.expect(secondsToSamples(1.0, 48000.0) == 48000, "one second at 48 kHz");
    checks.expect(secondsToSamples(0.0, 48000.0) == 0, "zero sample position");
    checks.expect(secondsToSamples(0.499, 1.0) == 0, "less than half a sample rounds down");
    checks.expect(secondsToSamples(0.5, 1.0) == 1, "half a sample rounds upward");
    checks.expect(secondsToSamples(1.499, 1.0) == 1, "below the next half-sample boundary");
    checks.expect(secondsToSamples(1.5, 1.0) == 2, "next half-sample boundary rounds upward");
    checks.expect(secondsToSamples(0.5 / 48000.0, 48000.0) == 1,
                  "half a sample at a realistic sample rate");

    const double maximum = std::numeric_limits<double>::max();
    const double minimumPositive = std::numeric_limits<double>::denorm_min();
    checks.near(secondsToBeats(maximum, 30.0), maximum / 2.0,
                "valid result survives intermediate multiplication overflow");
    checks.near(beatsToSeconds(maximum, 120.0), maximum / 2.0,
                "inverse conversion avoids intermediate overflow");
    checks.expect(secondsToBeats(minimumPositive, 60.0) == minimumPositive,
                  "subnormal position survives an identity conversion");
    checks.expect(beatsToSeconds(0.0, minimumPositive) == 0.0,
                  "zero position survives a tiny valid rate");
    checks.expect(secondsToSamples(minimumPositive, minimumPositive) == 0,
                  "tiny positive sample count rounds to zero");

    constexpr double sampleLimit = 0x1p63;
    const double lastRepresentable = std::nextafter(sampleLimit, 0.0);
    checks.expect(secondsToSamples(lastRepresentable, 1.0) == INT64_C(9223372036854774784),
                  "largest double sample position below int64 limit is safe");
    checks.throws<std::overflow_error>([&] { (void)secondsToSamples(sampleLimit, 1.0); },
                                       "2^63 samples is rejected before integer conversion");
    checks.throws<std::overflow_error>([&] { (void)secondsToSamples(maximum, maximum); },
                                       "sample product overflow is explicit");
    checks.throws<std::overflow_error>([&] { (void)secondsToBeats(maximum, maximum); },
                                       "beat result overflow is explicit");
    checks.throws<std::overflow_error>([&] { (void)beatsToSeconds(maximum, minimumPositive); },
                                       "seconds result overflow is explicit");

    const std::array invalidPositions {
        -1.0, std::numeric_limits<double>::infinity(),
        -std::numeric_limits<double>::infinity(), std::numeric_limits<double>::quiet_NaN()
    };
    for (const double position : invalidPositions) {
        checks.throws<std::invalid_argument>([&] { (void)secondsToBeats(position, 120.0); },
                                            "invalid seconds position is rejected");
        checks.throws<std::invalid_argument>([&] { (void)beatsToSeconds(position, 120.0); },
                                            "invalid beat position is rejected");
        checks.throws<std::invalid_argument>([&] { (void)secondsToSamples(position, 48000.0); },
                                            "invalid sample source position is rejected");
    }

    const std::array invalidRates {
        0.0, -1.0, std::numeric_limits<double>::infinity(),
        -std::numeric_limits<double>::infinity(), std::numeric_limits<double>::quiet_NaN()
    };
    for (const double rate : invalidRates) {
        checks.throws<std::invalid_argument>([&] { (void)secondsToBeats(1.0, rate); },
                                            "invalid tempo is rejected in forward conversion");
        checks.throws<std::invalid_argument>([&] { (void)beatsToSeconds(1.0, rate); },
                                            "invalid tempo is rejected in inverse conversion");
        checks.throws<std::invalid_argument>([&] { (void)secondsToSamples(1.0, rate); },
                                            "invalid sample rate is rejected");
    }
}

void testRevisionGuard(Checks& checks)
{
    using emusician::commands::RevisionGuard;
    using emusician::commands::ValidationResult;

    checks.throws<std::invalid_argument>([] { RevisionGuard invalid(""); },
                                        "empty project ID is rejected on construction");
    RevisionGuard guard("project-A");
    checks.expect(guard.projectId() == "project-A" && guard.revision() == 0,
                  "new project guard starts at revision zero");
    checks.expect(guard.validate("request-1", "project-A", 0) == ValidationResult::Accepted,
                  "valid request passes preflight");
    checks.expect(guard.validate("request-1", "project-A", 0) == ValidationResult::Accepted
                      && guard.revision() == 0,
                  "preflight is read-only and does not reserve request IDs");
    checks.expect(guard.validate("", "project-A", 0) == ValidationResult::InvalidRequest,
                  "empty request ID is invalid");
    checks.expect(guard.validate("request-1", "", 0) == ValidationResult::InvalidRequest,
                  "missing project ID is invalid");
    checks.expect(guard.validate("request-1", "project-B", 0) == ValidationResult::WrongProject,
                  "wrong project is rejected");
    checks.expect(guard.validate("request-1", "project-A", 1) == ValidationResult::Conflict,
                  "future revision is rejected");

    checks.expect(guard.commit("request-1", "project-B", 0) == ValidationResult::WrongProject
                      && guard.revision() == 0,
                  "commit cannot bypass project validation");
    checks.expect(guard.commit("", "project-A", 0) == ValidationResult::InvalidRequest
                      && guard.revision() == 0,
                  "commit cannot bypass request validation");
    checks.expect(guard.commit("request-1", "project-A", 0) == ValidationResult::Accepted
                      && guard.revision() == 1,
                  "successful edit records request and advances revision once");
    checks.expect(guard.validate("request-1", "project-A", 0) == ValidationResult::Duplicate,
                  "retry is duplicate even when it carries the old revision");
    checks.expect(guard.commit("request-1", "project-A", 1) == ValidationResult::Duplicate
                      && guard.revision() == 1,
                  "repeated commit does not advance revision");
    checks.expect(guard.commit("request-2", "project-A", 0) == ValidationResult::Conflict
                      && guard.revision() == 1,
                  "stale request cannot mutate bookkeeping");
    checks.expect(guard.commit("request-2", "project-A", 1) == ValidationResult::Accepted
                      && guard.revision() == 2,
                  "previously rejected ID can be retried with a valid revision");

    checks.expect(guard.validate("request-3", "project-A", 2) == ValidationResult::Accepted,
                  "request can be preflighted before another edit");
    checks.expect(guard.commit("request-4", "project-A", 2) == ValidationResult::Accepted,
                  "intervening edit advances the project");
    checks.expect(guard.commit("request-3", "project-A", 2) == ValidationResult::Conflict
                      && guard.revision() == 3,
                  "commit rechecks a request invalidated since preflight");

    RevisionGuard reopened("project-A", 42);
    checks.expect(reopened.revision() == 42
                      && reopened.validate("request-1", "project-A", 42) == ValidationResult::Accepted,
                  "restored revision starts a new session-local deduplication ledger");
    RevisionGuard exhausted("project-A", std::numeric_limits<std::uint64_t>::max());
    checks.throws<std::overflow_error>(
        [&] { (void)exhausted.commit("request-overflow", "project-A", exhausted.revision()); },
        "revision exhaustion is explicit");
    checks.expect(exhausted.revision() == std::numeric_limits<std::uint64_t>::max()
                      && exhausted.validate("request-overflow", "project-A", exhausted.revision())
                          == ValidationResult::Accepted,
                  "revision overflow does not record the request or wrap the revision");
}

} // namespace

int main()
{
    Checks checks;
    testTime(checks);
    testRevisionGuard(checks);
    return checks.finish();
}