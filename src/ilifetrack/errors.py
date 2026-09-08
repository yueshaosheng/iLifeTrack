"""Domain errors that are safe to classify without logging sensitive payloads."""


class ILifeTrackError(Exception):
    """Base error."""


class ConfigurationError(ILifeTrackError):
    """The local configuration is incomplete or invalid."""


class AuthenticationRequired(ILifeTrackError):
    """The iCloud session is absent, invalid, or requires user interaction."""


class ProviderNetworkError(ILifeTrackError):
    """The provider could not be reached."""


class ProviderResponseError(ILifeTrackError):
    """The provider returned an unsupported or invalid response."""


class CommunicationAccessError(ILifeTrackError):
    """The local Messages or call-history database is not readable."""
