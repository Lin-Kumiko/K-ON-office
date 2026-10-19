import { expect, test } from '@playwright/test'

test('访客可浏览公开页面，想操作时提示先登录；注册后才能登录', async ({ page }) => {
  // anonymous visit: public home, title is always the company name
  await page.goto('/')
  await expect(page).toHaveURL(/\/dashboard/)
  await expect(page).toHaveTitle('放学后茶会')
  await expect(page.locator('[data-test=public-facts]')).toContainText('名成员')
  await expect(page.locator('[data-test=header-login]')).toBeVisible()
  await expect(page.locator('[data-test=menu-system]')).toHaveCount(0)

  // public pages open without login
  await page.locator('[data-test=menu-announcements]').click()
  await expect(page).toHaveURL(/\/announcements/)
  await page.locator('[data-test=menu-org]').click()
  await expect(page.getByText('登录后可以查看部门人员')).toBeVisible()
  await expect(page).toHaveTitle('放学后茶会')

  // an operation asks the visitor to log in
  await page.locator('[data-test=menu-leave]').click()
  const dialog = page.locator('.el-message-box')
  await expect(dialog).toContainText('请先登录')
  await expect(page).toHaveURL(/\/org/)
  await dialog.getByRole('button', { name: '去注册' }).click()
  await expect(page).toHaveURL(/\/register/)

  // login with an unknown account fails: registration comes first
  await page.locator('[data-test=tab-login]').click()
  await page.locator('input[data-test=auth-username]').fill('ui_newcomer')
  await page.locator('input[data-test=auth-password]').fill('Cake2026x')
  await page.locator('[data-test=auth-submit]').click()
  await expect(page.locator('[data-test=auth-error]')).toHaveText('用户名或密码错误')

  // register with just username + password, then log in
  await page.locator('[data-test=tab-register]').click()
  await expect(page.locator('form input')).toHaveCount(2)
  await page.locator('input[data-test=auth-username]').fill('ui_newcomer')
  await page.locator('input[data-test=auth-password]').fill('Cake2026x')
  await page.locator('[data-test=auth-submit]').click()
  const done = page.locator('.register-done')
  await expect(done).toContainText('注册成功')
  await expect(page).toHaveURL(/\/register/)
  await done.getByRole('button', { name: '去登录' }).click()
  await expect(page).toHaveURL(/\/login\?.*username=ui_newcomer/)
  await expect(page.locator('[data-test=auth-notice]')).toHaveText('注册成功，请登录')
  await expect(page.locator('input[data-test=auth-username]')).toHaveValue('ui_newcomer')
  await page.locator('input[data-test=auth-password]').fill('Cake2026x')
  await page.locator('[data-test=auth-submit]').click()
  await expect(page).toHaveURL(/^https?:\/\/[^/]+\/(leave|dashboard)(\?|$)/)

  // now the visitor is a member and can operate
  await page.goto('/attendance')
  await page.locator('[data-test=punch-now]').click()
  await expect(page.locator('[data-test=punch-result]')).toContainText('打卡成功')
  await expect(page).toHaveTitle('放学后茶会')
})
