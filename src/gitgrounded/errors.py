class GitGroundedError(Exception):
    pass


class ConfigError(GitGroundedError):
    pass


class SourceError(GitGroundedError):
    pass


class TargetError(GitGroundedError):
    pass


class ProviderError(GitGroundedError):
    pass


class BudgetExceeded(GitGroundedError):
    pass


class EvidenceError(GitGroundedError):
    pass
