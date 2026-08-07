"""OpenShell policy loader."""

import os
import logging

logger = logging.getLogger(__name__)


def get_policy_path() -> str:
    """Return the configured policy file path."""
    return os.environ.get(
        "OPENSHELL_POLICY_PATH",
        os.path.join(
            os.path.dirname(__file__),
            "../../config/openshell/claim-evidence-policy.yaml",
        ),
    )


def policy_exists() -> bool:
    """Check if the configured policy file exists."""
    path = get_policy_path()
    return os.path.isfile(path)
