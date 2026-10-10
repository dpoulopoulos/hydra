"""Open and write client names, which hydra only ever holds encrypted.

The browser locks every client name under its owner's PIN before it leaves the
page, and the backend stores ciphertext it cannot read. This module does what
the page does, from the same PIN, so an agent can work with "Maria" rather than
with base64:

- Argon2id stretches the PIN into a key-encrypting key, with the parameters
  stored beside the vault rather than assumed.
- That key unwraps a random data key, and the data key opens each name.
- Every value is base64 of nonce || AES-GCM ciphertext || tag, exactly what
  `frontend/src/lib/income-vault.ts` writes, so a name written here reads in
  the page and one written there reads here.

The PIN arrives on the request, in the header named by `PIN_HEADER`, beside the
bearer token. It is never logged, never stored, and only the data key it
unlocks is remembered, for a short while, keyed by a hash rather than by the
PIN itself.
"""

import asyncio
import base64
import binascii
import hashlib
import os
import time
from typing import Any

from argon2.low_level import ARGON2_VERSION, Type, hash_secret_raw
from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from mcp.shared.exceptions import MCPError
from mcp.types import INVALID_REQUEST

from .config import settings

# Not an X- header: RFC 6648 retired that prefix.
PIN_HEADER = "Hydra-Clients-Pin"

NONCE_BYTES = 12
KEY_BYTES = 32

SUPPORTED_KDF = "argon2id"

# Each derivation holds the vault's memory cost, 64 MiB by default, for as long
# as it runs. A handful at once is plenty for one household's agent, and a cap
# keeps a burst of calls from taking the container's memory with it.
_derivations = asyncio.Semaphore(2)

LOCKED = (
    f"Client names are locked. Add your hydra PIN to the MCP connection as the {PIN_HEADER} header, "
    "or refer to the client by id."
)
WRONG_PIN = f"The PIN in the {PIN_HEADER} header did not unlock the client names. Check it in the MCP connection."


class Keyring:
    """The current person's data key, for one tool call, or the lack of one.

    A client belongs to whoever added them, and their name is under that
    person's key. Somebody else's names are not an error to read: they come
    back as None, which is what the page shows them as too.
    """

    def __init__(self, dek: bytes | None, user_id: str | None) -> None:
        """Initialize the keyring.

        Args:
            dek: The unwrapped data key, or None when no PIN was given.
            user_id: The person the token belongs to.
        """
        self._aead = AESGCM(dek) if dek is not None else None
        self.user_id = user_id

    @property
    def unlocked(self) -> bool:
        """Whether names can be read and written."""
        return self._aead is not None

    def owns(self, row: dict[str, Any]) -> bool:
        """Whether a client was added by the current person.

        Args:
            row: The client as hydra reports it.

        Returns:
            True when the client's name is under this person's key.
        """
        return self.user_id is not None and str(row.get("owner_user_id")) == self.user_id

    def read(self, ciphertext: str | None) -> str | None:
        """Open a name or a note.

        Args:
            ciphertext: The stored value, or None.

        Returns:
            The text, or None when there is nothing, no key, or the value is
            under somebody else's key.
        """
        if ciphertext is None or self._aead is None:
            return None

        try:
            packed = base64.b64decode(ciphertext, validate=True)
            return self._aead.decrypt(packed[:NONCE_BYTES], packed[NONCE_BYTES:], None).decode()
        except (InvalidTag, ValueError, binascii.Error):
            return None

    def write(self, text: str) -> str:
        """Lock a name or a note for storage.

        Args:
            text: What to lock.

        Returns:
            The value to send to hydra.

        Raises:
            ToolError: If no PIN was given, so there is no key to lock it with.
        """
        if self._aead is None:
            raise ToolError(LOCKED)

        nonce = os.urandom(NONCE_BYTES)
        return base64.b64encode(nonce + self._aead.encrypt(nonce, text.encode(), None)).decode()


def pin_of(ctx: Context | None) -> str | None:
    """Read the PIN off the request, if it carried one.

    Args:
        ctx: The tool's context.

    Returns:
        The PIN, or None if the request had no such header or no HTTP request
        behind it at all.
    """
    if ctx is None:
        return None

    try:
        headers = ctx.headers
    except ValueError:
        return None

    if not headers:
        return None

    wanted = PIN_HEADER.lower()
    for key, value in headers.items():
        if key.lower() == wanted:
            return value.strip() or None
    return None


async def keyring(ctx: Context | None, token: str) -> Keyring:
    """Build the keyring for one tool call.

    With no PIN on the request this is a locked keyring rather than an error,
    so the figures stay readable and only the names go missing.

    Args:
        ctx: The tool's context, which carries the request headers.
        token: The hydra API token to present.

    Returns:
        The keyring.

    Raises:
        MCPError: If a PIN was given and it is wrong. No rewording of a tool's
            arguments fixes that, so the host hears it rather than the model.
        ToolError: If this person has never set up a PIN.
    """
    access_token = get_access_token()
    user_id = access_token.client_id if access_token is not None else None

    pin = pin_of(ctx)
    if pin is None:
        return Keyring(None, user_id)

    from .tools._common import hydra

    vault = await hydra().get("/income/vault", token=token, subject="PIN for client names")
    return Keyring(await _unlock(pin, vault), user_id)


# The data keys already unwrapped, by a hash of what unwrapped them. Stateless
# HTTP means every tool call arrives alone, and paying Argon2id on each of them
# would make an agent turn several seconds slower for no gain in safety: the
# vault is still fetched with the caller's token every time.
_unwrapped: dict[str, tuple[float, bytes]] = {}


async def _unlock(pin: str, vault: dict[str, Any]) -> bytes:
    """Unwrap the data key with a PIN.

    Args:
        pin: The PIN.
        vault: The vault as hydra reports it.

    Returns:
        The data key.

    Raises:
        MCPError: If the PIN does not open the vault.
        ToolError: If the vault uses a key derivation this server cannot do.
    """
    if vault["kdf"] != SUPPORTED_KDF:
        raise ToolError(f"The client names are locked with {vault['kdf']}, which this server cannot open.")

    cache_key = hashlib.sha256("\0".join([pin, vault["kdf_salt"], vault["wrapped_dek"]]).encode()).hexdigest()
    now = time.monotonic()
    cached = _unwrapped.get(cache_key)
    if cached is not None and now < cached[0]:
        return cached[1]

    async with _derivations:
        kek = await asyncio.to_thread(_derive, pin, vault)

    try:
        packed = base64.b64decode(vault["wrapped_dek"], validate=True)
        dek = AESGCM(kek).decrypt(packed[:NONCE_BYTES], packed[NONCE_BYTES:], None)
    except (InvalidTag, ValueError, binascii.Error):
        # A wrong PIN and a damaged vault are the same failure: the tag did
        # not verify. Never echo the PIN back.
        raise MCPError(INVALID_REQUEST, WRONG_PIN) from None

    for stale in [key for key, (expires_at, _) in _unwrapped.items() if now >= expires_at]:
        del _unwrapped[stale]
    _unwrapped[cache_key] = (now + settings.CLIENTS_KEY_CACHE_SECONDS, dek)
    return dek


def _derive(pin: str, vault: dict[str, Any]) -> bytes:
    """Stretch a PIN into the key that wraps the data key.

    The same Argon2id the page runs through hash-wasm: version 0x13, a 32 byte
    output, and whatever cost the vault was created with.

    Args:
        pin: The PIN.
        vault: The vault, carrying the salt and the cost parameters.

    Returns:
        The key-encrypting key.
    """
    return hash_secret_raw(
        secret=pin.encode(),
        salt=base64.b64decode(vault["kdf_salt"]),
        time_cost=vault["kdf_iterations"],
        memory_cost=vault["kdf_memory_kib"],
        parallelism=vault["kdf_parallelism"],
        hash_len=KEY_BYTES,
        type=Type.ID,
        version=ARGON2_VERSION,
    )
