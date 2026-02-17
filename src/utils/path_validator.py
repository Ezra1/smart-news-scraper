from pathlib import Path


def validate_path(user_path: str, base_dir: str | Path | None = None, must_exist: bool = False) -> Path:
    """
    Validate and normalize user-provided path to prevent traversal outside an allowed base.

    Args:
        user_path: User-provided path string.
        base_dir: Optional base directory to restrict paths to.
        must_exist: If True, raise if path doesn't exist.

    Raises:
        ValueError: If path traversal is detected, path is empty, or path does not exist when required.

    Returns:
        Path: Resolved, validated path.
    """
    if not user_path:
        raise ValueError("Path cannot be empty")

    path = Path(user_path).expanduser().resolve()

    if base_dir:
        base = Path(base_dir).expanduser().resolve()
        try:
            path.relative_to(base)
        except ValueError:
            raise ValueError(f"Path must be within {base}")

    if must_exist and not path.exists():
        raise ValueError(f"Path does not exist: {path}")

    return path

