import { expect, type Page } from '@playwright/test'

export const PASSWORD = process.env.E2E_PASSWORD as string

export async function login(page: Page, username: string, password = PASSWORD) {
  await page.goto('/login')
  await page.locator('input[data-test=auth-username]').fill(username)
  await page.locator('input[data-test=auth-password]').fill(password)
  await page.locator('[data-test=auth-submit]').click()
  await expect(page).toHaveURL(/\/(dashboard|profile)/)
}

export async function logout(page: Page) {
  await page.evaluate(() => localStorage.removeItem('doe_token'))
  await page.goto('/login')
}

/** Pick an option of an Element Plus select; the listbox is resolved through the combobox's aria-controls
 * so a previous dropdown that is still fading out can never be matched. */
export async function pickOption(page: Page, trigger: ReturnType<Page['locator']>, text: string | RegExp) {
  await trigger.click()
  const combo = trigger.locator('input[role=combobox]').first()
  await expect(combo).toHaveAttribute('aria-expanded', 'true')
  const listId = await combo.getAttribute('aria-controls')
  await page.locator(`[id="${listId}"] .el-select-dropdown__item`).filter({ hasText: text }).first().click()
}

export async function fillDate(input: ReturnType<Page['locator']>, value: string) {
  await input.click()
  await input.fill(value)
  await input.press('Enter')
}

const pad = (n: number) => String(n).padStart(2, '0')
export const ymd = (d: Date) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`

/** Monday of the week `weeksAhead` weeks from now (avoids weekends). */
export function mondayAhead(weeksAhead: number): Date {
  const d = new Date()
  d.setHours(12, 0, 0, 0)
  const toMonday = (8 - d.getDay()) % 7 || 7
  d.setDate(d.getDate() + toMonday + 7 * (weeksAhead - 1))
  return d
}

export function addDays(d: Date, n: number): Date {
  const x = new Date(d)
  x.setDate(x.getDate() + n)
  return x
}

export async function expectSuccess(page: Page, text?: string | RegExp) {
  const msg = page.locator('.el-message--success').last()
  await expect(msg).toBeVisible()
  if (text) await expect(msg).toContainText(text)
}

export async function api(page: Page, method: string, url: string, body?: unknown) {
  return page.evaluate(async ([m, u, b]) => {
    const r = await fetch(u as string, { method: m as string, headers: { 'Content-Type': 'application/json',
      Authorization: `Bearer ${localStorage.getItem('doe_token')}` }, body: b ? JSON.stringify(b) : undefined })
    return { status: r.status, body: await r.json().catch(() => null) }
  }, [method, url, body])
}

/** Input/textarea for a data-test key, whether the attribute sits on a wrapper or on the element itself. */
export function field(scope: Page | ReturnType<Page['locator']>, key: string) {
  return scope.locator(`input[data-test="${key}"], textarea[data-test="${key}"], [data-test="${key}"] input, [data-test="${key}"] textarea`).first()
}
