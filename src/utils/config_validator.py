"""Utilities for resolving and loading Hydra configuration files.

This module provides helper functions to locate a configuration
directory and load Hydra configuration files using that directory.
It supports both absolute and relative paths and ensures that the
configuration directory exists before attempting to load configurations.

Functions:
    resolve_config_dir(config_dir):
        Resolve a configuration directory path.

    load_cfg(payload_config_dir, payload_config_name):
        Load a Hydra configuration from the specified directory and configuration name.
"""

from pathlib import Path

from hydra import initialize_config_dir, compose


def resolve_config_dir(config_dir: str) -> Path:
    """Resolve a configuration directory path.

    This function attempts to resolve the given 'config_dir' string to
    an absolute directory path. If the provided path is relative, it
    checks several candidate locations:
      1. Relative to the current working directory.
      2. Relative to the directory containing this module.
      3. Using only the last component of the path in the current working directory.

    Args:
        config_dir (str): The configuration directory path, either absolute or relative.

    Returns:
        (Path): A 'Path' object pointing to the resolved configuration directory.

    Raises:
        FileNotFoundError: If none of the candidate paths exist as a directory.
    """
    path = Path(config_dir)
    candidates = [path] if path.is_absolute() else []
    if not path.is_absolute():
        candidates.extend(
            [
                Path.cwd() / path,
                Path(__file__).resolve().parent / path,
                Path.cwd() / path.name,
            ]
        )

    for candidate in candidates:
        resolved = candidate.resolve()
        if resolved.is_dir():
            return resolved

    checked = ", ".join(str(candidate.resolve()) for candidate in candidates)
    raise FileNotFoundError(f"Config directory not found for {config_dir!r}. Checked: {checked}")


def load_cfg(payload_config_dir, payload_config_name):
    """Load a Hydra configuration from a directory.

    This function resolves the given configuration directory, initializes
    Hydra with that directory, and composes the configuration with the
    specified configuration name. The composed configuration is printed
    to stdout and returned.

    Args:
        payload_config_dir (str): Path to the configuration directory.
        payload_config_name (str): Name of the configuration file to load (without extension).

    Returns:
        (DictConfig): The composed Hydra configuration object.

    Raises:
        FileNotFoundError: If the configuration directory cannot be resolved.
        HydraException: If there is an error composing the configuration.
    """
    config_dir = str(resolve_config_dir(payload_config_dir))
    with initialize_config_dir(config_dir=config_dir, version_base=None):
        return compose(config_name=payload_config_name)
    return None
