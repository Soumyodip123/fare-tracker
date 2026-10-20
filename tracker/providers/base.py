class ProviderError(Exception):
    """The source failed. Never converted into a price."""


class NoResults(ProviderError):
    """The source answered but returned no flights."""
