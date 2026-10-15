import json
import logging

from app import config

log = logging.getLogger(__name__)

_users = None


def _load():
    global _users
    if _users is None:
        with open(config.USERS_FILE) as f:
            _users = json.load(f)
    return _users


def get_groups(user_id):
    """Return the list of groups a user belongs to.

    TODO: this reads a static json file for now. Swap for the identity
    service lookup once we have a service account for it.
    """
    user = _load().get(user_id)
    if not user:
        log.warning("unknown user %s", user_id)
        return []
    return user.get("groups", [])
