from .serpapi import SerpApiProvider

# To add a source: write a class with `name`, `label` and `search(cfg) -> list[Flight]`
# that raises ProviderError/NoResults on failure, then register it here.
PROVIDERS = {"serpapi": SerpApiProvider}


def get_provider(name: str):
    if name not in PROVIDERS:
        raise ValueError(f"Unknown provider {name!r}. Available: {', '.join(PROVIDERS)}")
    return PROVIDERS[name]()
