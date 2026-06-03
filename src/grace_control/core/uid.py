# ############################################################################
# AI_HEADER: uid
# ROLE: NanoID-based UID generation for Feature/Wave/Packet identity.
# ############################################################################

# START_MODULE_CONTRACT
# purpose: Generate short NanoID strings with entity-specific prefixes.
#          generate_unique_id() retries on DB collision.
# inputs: None or DB model.
# returns: str uid.
# side_effects: None.
# emitted_logs: None.
# error_behavior: generate_unique_id raises RuntimeError after max_attempts.
# END_MODULE_CONTRACT

# START_MODULE_MAP
# mapping:
#   - function: nanoid
#   - function: new_feature_uid
#   - function: new_wave_uid
#   - function: new_packet_uid
#   - function: new_run_uid
#   - function: generate_unique_id
# END_MODULE_MAP

from __future__ import annotations

import secrets

_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"


def nanoid(size: int = 10) -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(size))


def new_feature_uid() -> str:
    return f"feat_{nanoid(10)}"


def new_wave_uid() -> str:
    return f"wave_{nanoid(10)}"


def new_packet_uid() -> str:
    return f"pkt_{nanoid(10)}"


def new_run_uid() -> str:
    return f"run_{nanoid(10)}"


def generate_unique_id(db, model, factory, *, max_attempts: int = 5) -> str:
    for _ in range(max_attempts):
        value = factory()
        if db.query(model).filter_by(id=value).first() is None:
            return value
    raise RuntimeError(f"failed to generate unique id after {max_attempts} attempts")
