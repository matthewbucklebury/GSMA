"""Secret handling (brief section 4): secrets come from environment variables
and are never written to the repo, the data directories, logs, or manifests.

Adapters must fetch keys through these helpers at the moment of use and must
not stash the value on the adapter instance, in config, or in any output.
"""
import os

OPENCELLID_ENV_VAR = "OPENCELLID_API_KEY"


class MissingSecretError(RuntimeError):
    pass


def get_secret(env_var: str) -> str:
    """Read a secret from the environment; raise a readable error if absent."""
    value = os.environ.get(env_var, "").strip()
    if not value:
        raise MissingSecretError(
            f"Environment variable {env_var} is not set. Export it before "
            f"running this adapter; secrets are never read from files.")
    return value


def get_opencellid_key() -> str:
    return get_secret(OPENCELLID_ENV_VAR)
