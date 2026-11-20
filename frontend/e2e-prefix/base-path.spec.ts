import { expect, test } from '@playwright/test'

const PREFIX = '/k-on'
const PASSWORD = process.env.E2E_PASSWORD as string

test('子路径部署：资源、路由、接口都带前缀，深链接刷新正常', async ({ page }) => {
  const origin = new URL(test.info().project.use.baseURL as string).origin
  const outside: string[] = [] // requests to the app that left the prefix
  const failed: string[] = [] // 4xx/5xx responses from the app
  page.on('request', (req) => {
    const u = new URL(req.url())
    if (u.origin === origin && u.pathname !== PREFIX && !u.pathname.startsWith(`${PREFIX}/`)) outside.push(u.pathname)
  })
  page.on('response', (res) => {
    if (res.url().startsWith(origin) && res.status() >= 400) failed.push(`${res.status()} ${new URL(res.url()).pathname}`)
  })

  // the login page loads its logo (a public asset) from under the prefix
  await page.goto(`${PREFIX}/login`)
  const logo = page.locator('img.logo').first()
  await expect(logo).toBeVisible()
  expect(await logo.evaluate((img: HTMLImageElement) => img.naturalWidth)).toBeGreaterThan(0)

  // logging in calls the API under the prefix and lands on a page under the prefix
  await page.locator('input[data-test=auth-username]').fill('yui')
  await page.locator('input[data-test=auth-password]').fill(PASSWORD)
  await page.locator('[data-test=auth-submit]').click()
  await expect(page).toHaveURL(new RegExp(`${PREFIX}/(dashboard|profile)`))

  // menu navigation keeps the prefix
  await page.locator('[data-test=menu-attendance]').click()
  await expect(page).toHaveURL(new RegExp(`${PREFIX}/attendance$`))
  await expect(page.locator('[data-test=punch-now]')).toBeVisible()

  // a deep link survives a reload (the SPA fallback is served under the prefix too)
  await page.reload()
  await expect(page).toHaveURL(new RegExp(`${PREFIX}/attendance$`))
  await expect(page.locator('[data-test=punch-now]')).toBeVisible()

  // the API answers under the prefix and is not served outside it (nginx only forwards /k-on/)
  expect((await page.request.get(`${PREFIX}/api/health`)).status()).toBe(200)
  expect((await page.request.get('/api/health')).status()).toBe(404)

  // logging out lands back on the login page under the prefix
  await page.evaluate(() => localStorage.removeItem('doe_token'))
  await page.goto(`${PREFIX}/attendance`)
  await expect(page).toHaveURL(new RegExp(`${PREFIX}/login`))

  expect(outside, 'requests that left the sub-path').toEqual([])
  expect(failed, 'failed responses').toEqual([])
})
