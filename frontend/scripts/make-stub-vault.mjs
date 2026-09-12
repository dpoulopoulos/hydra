// Makes the income vault fixture that stub-backend.Caddyfile serves.
//
// The walk in csp-walk.mjs opens the vault on the income screen, which is the
// one place the app compiles WebAssembly: hash-wasm's Argon2id stretches the
// PIN. A made up wrapped key would fail to unwrap, so the stub has to serve a
// real one, and this is where it comes from.
//
// Everything here is fixed on purpose -- the PIN, the salt, the data key, the
// nonces -- so running it again prints exactly what the stub already carries.
// That is what makes the fixture reviewable: a change to it is a change to
// this file, not a fresh pile of base64.
//
// Run it from the frontend directory, `node scripts/make-stub-vault.mjs`, and
// paste what it prints into scripts/stub-backend.Caddyfile.

import { argon2id } from 'hash-wasm'
import { webcrypto as crypto } from 'node:crypto'

/** What the walk types into the unlock dialog. */
const PIN = '135790'

/** The same parameters DEFAULT_KDF_PARAMS names, since the stub serves those. */
const MEMORY_KIB = 65536
const ITERATIONS = 3
const PARALLELISM = 1

// Sixteen bytes and twelve bytes, which is what a salt and an AES-GCM nonce
// are. Readable text rather than random bytes, so that what is fixed looks
// fixed to whoever reads the base64 in the stub.
const SALT = Buffer.from('stub-salt-000000', 'utf8')
const DATA_KEY = Buffer.from('stub-data-key-0000000000000000!!', 'utf8')
const WRAP_NONCE = Buffer.from('stubnonce-01', 'utf8')
const NAME_NONCE = Buffer.from('stubnonce-02', 'utf8')

/** The name the screen shows once the vault is open. */
const CLIENT_NAME = 'Wanda Walker'

async function importKey(raw, usages) {
  return crypto.subtle.importKey('raw', raw, 'AES-GCM', false, usages)
}

/** nonce || ciphertext || tag, packed the way income-vault.ts packs it. */
async function seal(key, nonce, plaintext) {
  const sealed = await crypto.subtle.encrypt({ name: 'AES-GCM', iv: nonce }, key, plaintext)
  return Buffer.concat([nonce, Buffer.from(sealed)]).toString('base64')
}

const kek = await importKey(
  await argon2id({
    password: PIN,
    salt: SALT,
    memorySize: MEMORY_KIB,
    iterations: ITERATIONS,
    parallelism: PARALLELISM,
    hashLength: DATA_KEY.length,
    outputType: 'binary',
  }),
  ['encrypt'],
)

console.log(`the PIN the walk types: ${PIN}`)
console.log(`kdf_salt:               ${SALT.toString('base64')}`)
console.log(`wrapped_dek:            ${await seal(kek, WRAP_NONCE, DATA_KEY)}`)
console.log(
  `name_ct (${CLIENT_NAME}):  ${await seal(
    await importKey(DATA_KEY, ['encrypt']),
    NAME_NONCE,
    Buffer.from(CLIENT_NAME, 'utf8'),
  )}`,
)
