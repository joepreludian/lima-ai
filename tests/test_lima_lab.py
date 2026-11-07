"""Pure helpers of the real-VM suite, checked without a VM."""

import json

from lima_ai.render import GUEST_BACKUPS
from tests.integration.test_lima import stale_base_reason

OLD = {
    "name": "dev-base",
    "config": {"mounts": [{"location": "/Users/me/Developer/backups/docker", "mountPoint": "/backups/docker"}]},
}
NEW = {
    "name": "dev-base",
    "config": {"mounts": [{"location": "/Users/me/Developer/backups/docker", "mountPoint": GUEST_BACKUPS}]},
}


def test_stale_base_reason_names_the_old_mount_and_the_fix():
    reason = stale_base_reason(json.dumps(OLD))
    assert reason is not None
    assert "/backups/docker" in reason
    assert "lima-ai base --rebuild" in reason


def test_stale_base_reason_is_none_for_a_current_base():
    assert stale_base_reason(json.dumps(NEW)) is None
