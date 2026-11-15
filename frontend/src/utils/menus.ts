import { appRoutes } from '@/router'
import { useAuth } from '@/stores/auth'

export interface MenuEntry {
  path: string
  name: string
  title: string
  icon: string
  locked: boolean
}

/** Pages the current user (or visitor) can see in navigation. Visitors see everything except administration;
 * pages they cannot open yet are marked locked and ask for login when opened (router guard). */
export function visibleMenus(auth: ReturnType<typeof useAuth>): MenuEntry[] {
  return appRoutes
    .filter((r) => !r.meta?.hidden)
    .filter((r) => (auth.loggedIn
      ? auth.canAny(r.meta?.perm as string | string[] | undefined) || (r.name === 'attendance' && auth.can('attendance:punch'))
      : !r.meta?.adminOnly))
    .map((r) => ({ path: r.path, name: r.name as string, title: r.meta?.title as string, icon: r.meta?.icon as string,
                   locked: !auth.loggedIn && !r.meta?.visitor }))
}
