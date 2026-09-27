/**
 * Links you've created, remembered in this browser only, so you can find their results again.
 * Browser storage can be missing or blocked (private windows), so every access is guarded.
 */
export type MyLink = { slug: string; token: string; text: string; created: string }

const KEY = 'misconstrue.myLinks'
const MAX = 20

export function loadLinks(): MyLink[] {
  try {
    const raw = localStorage.getItem(KEY)
    return raw ? (JSON.parse(raw) as MyLink[]) : []
  } catch {
    return []
  }
}

export function rememberLink(link: MyLink): void {
  try {
    const links = [link, ...loadLinks().filter((l) => l.token !== link.token)].slice(0, MAX)
    localStorage.setItem(KEY, JSON.stringify(links))
  } catch {
    // Not remembered; the results link on screen still works.
  }
}

export function forgetLink(token: string): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(loadLinks().filter((l) => l.token !== token)))
  } catch {
    // ignore
  }
}
