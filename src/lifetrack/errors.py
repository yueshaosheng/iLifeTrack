"""Domain errors that are safe to classify without logging sensitive payloads."""


class LifeTrackError(Exception):
    """Base error."""


class ConfigurationError(LifeTrackError):
    """The local configuration is incomplete or invalid."""


class AuthenticationRequired(LifeTrackError):
    """The iCloud session is absent, invalid, or requires user interaction."""


class ProviderNetworkError(LifeTrackError):
    """The provider could not be reached."""


class ProviderResponseError(LifeTrackError):
    """The provider returned an unsupported or invalid response."""


class CommunicationAccessError(LifeTrackError):
    """The local Messages or call-history database is not readable."""
