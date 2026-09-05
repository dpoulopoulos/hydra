import { useAuth } from '@/hooks/use-auth'
import { useDecrypted } from '@/hooks/use-vault'

/**
 * A client's name, or dots when it cannot be read.
 *
 * Dots rather than initials or a stable alias: an alias would still let anyone
 * looking over your shoulder count how often a particular person comes, and
 * initials give the name away outright.
 *
 * There are two reasons a name shows as dots, and they are worth telling apart
 * for anyone using a screen reader. Your own client is hidden because the vault
 * is locked, and typing your PIN reveals them. Another household member's
 * client is under their key, so no PIN of yours will ever open it.
 */
export function ClientName({
  nameCt,
  ownerUserId,
  fallback = '••••••••',
}: {
  nameCt: string
  /** Who the name is encrypted for. Omit when it is known to be the reader's. */
  ownerUserId?: string
  fallback?: string
}) {
  const { user } = useAuth()
  const isMine = ownerUserId === undefined || ownerUserId === user?.id
  // Not even attempted for somebody else's client: the decrypt could only fail,
  // and an attempt that always fails is noise rather than a safeguard.
  const name = useDecrypted(isMine ? nameCt : null)

  if (name === null) {
    return (
      <span
        className="text-muted-foreground tracking-widest select-none"
        aria-label={isMine ? 'Hidden until you unlock names' : "Another member's client"}
      >
        {fallback}
      </span>
    )
  }

  return <span>{name}</span>
}
