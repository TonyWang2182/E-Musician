#pragma once

#include <cstdint>
#include <functional>
#include <limits>
#include <stdexcept>
#include <string>
#include <string_view>
#include <unordered_set>
#include <utility>

namespace emusician::commands {

enum class ValidationResult {
    Accepted,
    Duplicate,
    WrongProject,
    Conflict,
    InvalidRequest
};

// Confined to the single project-editing context; this class is not thread-safe.
// Playback positions and meter updates do not pass through this guard.
class RevisionGuard {
public:
    explicit RevisionGuard(std::string projectId, std::uint64_t initialRevision = 0)
        : projectId_(std::move(projectId)), revision_(initialRevision)
    {
        if (projectId_.empty())
            throw std::invalid_argument("Project ID must not be empty");
    }

    [[nodiscard]] const std::string& projectId() const noexcept { return projectId_; }
    [[nodiscard]] std::uint64_t revision() const noexcept { return revision_; }

    // Pure preflight: validating a request neither reserves its ID nor advances
    // the revision. Deduplication precedes revision checking, so a retry of an
    // already committed request remains Duplicate even with its old revision.
    [[nodiscard]] ValidationResult validate(
        std::string_view requestId,
        std::string_view projectId,
        std::uint64_t expectedRevision) const
    {
        if (requestId.empty() || projectId.empty())
            return ValidationResult::InvalidRequest;
        if (projectId != projectId_)
            return ValidationResult::WrongProject;
        if (committedRequestIds_.contains(requestId))
            return ValidationResult::Duplicate;
        if (expectedRevision != revision_)
            return ValidationResult::Conflict;
        return ValidationResult::Accepted;
    }

    // Call after the corresponding edit succeeds, in the same serialized
    // editing context. Recheck the complete request instead of trusting a prior
    // validation. This records bookkeeping; it does not apply or undo edits.
    [[nodiscard]] ValidationResult commit(
        std::string_view requestId,
        std::string_view projectId,
        std::uint64_t expectedRevision)
    {
        const auto result = validate(requestId, projectId, expectedRevision);
        if (result != ValidationResult::Accepted)
            return result;
        if (revision_ == std::numeric_limits<std::uint64_t>::max())
            throw std::overflow_error("Project revision exhausted");

        // Insert before incrementing so allocation failure leaves both unchanged.
        committedRequestIds_.emplace(requestId);
        ++revision_;
        return ValidationResult::Accepted;
    }

private:
    struct RequestIdHash {
        using is_transparent = void;
        std::size_t operator()(std::string_view value) const noexcept
        {
            return std::hash<std::string_view>{}(value);
        }
    };

    std::string projectId_;
    std::uint64_t revision_;
    // Session-local IDs only: restoring a revision does not restore this ledger.
    std::unordered_set<std::string, RequestIdHash, std::equal_to<>> committedRequestIds_;
};

} // namespace emusician::commands