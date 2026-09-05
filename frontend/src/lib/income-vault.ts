/**
 * Client-side encryption for the names of the people you see.
 *
 * The server stores ciphertext and nothing else. Your PIN never leaves this
 * browser, so a copy of the database is a list of fees and dates with nobody's
 * name attached to it.
 *
 * The shape is ordinary envelope encryption, and it is worth saying why:
 *
 * - A random 256 bit **data key** encrypts every name. It never changes.
 * - The PIN is stretched by Argon2id into a **key-encrypting key**, and that
 *   wraps the data key.
 *
 * Changing the PIN therefore re-wraps one small key and touches no client row.
 * Encrypting the names with the PIN directly would mean re-encrypting every
 * name on every PIN change, and losing all of them if that ever half finished.
 *
 * An honest limit, because the page says it out loud too: six digits is a
 * million guesses. Argon2id at these parameters costs roughly half a second a
 * guess, so somebody holding a copy of the database needs days rather than
 * seconds. That is the protection on offer, and no more.
 */
import { argon2id } from 'hash-wasm'

/** AES-GCM needs a 96 bit nonce, and using anything else weakens it. */
const NONCE_BYTES = 12
const SALT_BYTES = 16
const KEY_BYTES = 32

/**
 * Argon2id parameters for a new vault.
 *
 * 64 MiB and three passes is the cost that makes a short PIN worth anything at
 * all. They are stored alongside the vault rather than assumed, so they can be
 * raised later without stranding a vault created under the old ones.
 */
export const DEFAULT_KDF_PARAMS = {
  kdf: 'argon2id',
  kdf_memory_kib: 65536,
  kdf_iterations: 3,
  kdf_parallelism: 1,
} as const

/** The shortest PIN worth calling one. Fewer digits is not a lock. */
export const MIN_PIN_LENGTH = 6

export type KdfParams = {
  kdf_salt: string
  kdf_memory_kib: number
  kdf_iterations: number
  kdf_parallelism: number
}

/** Thrown when a PIN does not open the vault, or the stored data is damaged. */
export class VaultLockedError extends Error {
  constructor() {
    super('That PIN did not unlock the names.')
    this.name = 'VaultLockedError'
  }
}

function toBase64(bytes: Uint8Array): string {
  let binary = ''
  for (const byte of bytes) binary += String.fromCharCode(byte)
  return btoa(binary)
}

function fromBase64(value: string): Uint8Array {
  const binary = atob(value)
  const bytes = new Uint8Array(binary.length)
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i)
  return bytes
}

function randomBytes(length: number): Uint8Array {
  return crypto.getRandomValues(new Uint8Array(length))
}

/** Make a fresh salt for a brand new vault. */
export function newSalt(): string {
  return toBase64(randomBytes(SALT_BYTES))
}

/**
 * Stretch a PIN into the key that wraps the data key.
 *
 * Deliberately slow. That is the entire defence a six digit secret has.
 */
async function deriveKek(pin: string, params: KdfParams): Promise<CryptoKey> {
  const raw = await argon2id({
    password: pin,
    salt: fromBase64(params.kdf_salt),
    memorySize: params.kdf_memory_kib,
    iterations: params.kdf_iterations,
    parallelism: params.kdf_parallelism,
    hashLength: KEY_BYTES,
    outputType: 'binary',
  })

  return crypto.subtle.importKey('raw', raw as BufferSource, 'AES-GCM', false, [
    'encrypt',
    'decrypt',
  ])
}

async function encryptBytes(key: CryptoKey, plaintext: Uint8Array): Promise<string> {
  const nonce = randomBytes(NONCE_BYTES)
  const ciphertext = new Uint8Array(
    await crypto.subtle.encrypt(
      { name: 'AES-GCM', iv: nonce as BufferSource },
      key,
      plaintext as BufferSource,
    ),
  )

  // nonce || ciphertext || tag, so one string carries everything needed to
  // reverse it and there is no second field to lose.
  const packed = new Uint8Array(nonce.length + ciphertext.length)
  packed.set(nonce)
  packed.set(ciphertext, nonce.length)
  return toBase64(packed)
}

async function decryptBytes(key: CryptoKey, packed: string): Promise<Uint8Array> {
  const bytes = fromBase64(packed)
  const nonce = bytes.slice(0, NONCE_BYTES)
  const ciphertext = bytes.slice(NONCE_BYTES)

  try {
    return new Uint8Array(
      await crypto.subtle.decrypt(
        { name: 'AES-GCM', iv: nonce as BufferSource },
        key,
        ciphertext as BufferSource,
      ),
    )
  } catch {
    // A wrong PIN and damaged data are the same failure here: the GCM tag did
    // not verify. That is the only PIN check there is, and it should stay the
    // only one. A separate "is this PIN right" field would be a free oracle
    // for somebody guessing offline.
    throw new VaultLockedError()
  }
}

/** Create a data key and wrap it under a new PIN. */
export async function createVault(
  pin: string,
): Promise<{ params: KdfParams; wrappedDek: string; dek: CryptoKey }> {
  const params: KdfParams = { ...DEFAULT_KDF_PARAMS, kdf_salt: newSalt() }
  const dekBytes = randomBytes(KEY_BYTES)
  const kek = await deriveKek(pin, params)

  return {
    params,
    wrappedDek: await encryptBytes(kek, dekBytes),
    dek: await importDek(dekBytes),
  }
}

/**
 * Unwrap the data key with a PIN.
 *
 * @throws VaultLockedError if the PIN is wrong.
 */
export async function unlockVault(
  pin: string,
  params: KdfParams,
  wrappedDek: string,
): Promise<CryptoKey> {
  const kek = await deriveKek(pin, params)
  return importDek(await decryptBytes(kek, wrappedDek))
}

/**
 * Re-wrap an already unlocked data key under a new PIN.
 *
 * The names are untouched, which is why changing a PIN is instant and cannot
 * leave half of them readable.
 */
export async function rewrapVault(
  dek: CryptoKey,
  pin: string,
): Promise<{ params: KdfParams; wrappedDek: string }> {
  const params: KdfParams = { ...DEFAULT_KDF_PARAMS, kdf_salt: newSalt() }
  const kek = await deriveKek(pin, params)
  const raw = new Uint8Array(await crypto.subtle.exportKey('raw', dek))

  return { params, wrappedDek: await encryptBytes(kek, raw) }
}

async function importDek(raw: Uint8Array): Promise<CryptoKey> {
  // Extractable, because changing the PIN has to re-wrap this exact key.
  return crypto.subtle.importKey('raw', raw as BufferSource, 'AES-GCM', true, [
    'encrypt',
    'decrypt',
  ])
}

/** Encrypt a name or a note for storage. */
export async function encryptText(dek: CryptoKey, text: string): Promise<string> {
  return encryptBytes(dek, new TextEncoder().encode(text))
}

/**
 * Decrypt a name or a note.
 *
 * @throws VaultLockedError if the stored value does not belong to this key.
 */
export async function decryptText(dek: CryptoKey, ciphertext: string): Promise<string> {
  return new TextDecoder().decode(await decryptBytes(dek, ciphertext))
}
