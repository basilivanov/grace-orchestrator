"""Backward compatibility aliases for old CLI names.

This module provides entry points for deprecated CLI command names to maintain
backward compatibility during the transition period.

Deprecated commands:
- prefect-grace -> grace
- gracectl -> grace

These aliases will be removed in a future major version.
"""

import sys
import warnings


def prefect_grace_main():
    """
    Backward compatibility entry point for 'prefect-grace' command.

    Redirects to 'grace' with deprecation warning.
    """
    warnings.warn(
        "The 'prefect-grace' command is deprecated. Use 'grace' instead.",
        DeprecationWarning,
        stacklevel=2
    )

    from prefect_grace.cli import main
    return main()


def gracectl_main():
    """
    Backward compatibility entry point for 'gracectl' command.

    Redirects to 'grace' with deprecation warning.
    """
    warnings.warn(
        "The 'gracectl' command is deprecated. Use 'grace' instead.",
        DeprecationWarning,
        stacklevel=2
    )

    from prefect_grace.cli import main
    return main()


if __name__ == "__main__":
    sys.exit(prefect_grace_main())
