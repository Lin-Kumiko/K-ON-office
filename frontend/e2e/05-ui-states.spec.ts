import { expect, test } from '@playwright/test'
import { field, login, mondayAhead, pickOption, ymd } from './helpers'

test('权限：普通员工看不到管理菜单，直接访问被拦截且后端拒绝', async ({ page }) => {
  await login(page, 'mika')
  await expect(page.locator('[data-test=menu-system]')).toHaveCount(0)
  await expect(page.locator('[data-test=menu-workflow]')).toHaveCount(0)
  await page.goto('/system')
  await expect(page.getByText('无权访问')).toBeVisible()
  const status = await page.evaluate(async () => (await fetch('/api/users', { headers: { Authorization: `Bearer ${localStorage.getItem('doe_token')}` } })).status)
  expect(status).toBe(403)
})

test('登录失败提示、深色模式与手机布局', async ({ page }) => {
  await page.goto('/login')
  await page.locator('input[data-test=auth-username]').fill('yui')
  await page.locator('input[data-test=auth-password]').fill('wrong-password-1')
  await page.locator('[data-test=auth-submit]').click()
  await expect(page.locator('[data-test=auth-error]')).toHaveText('用户名或密码错误')
  await login(page, 'yui')
  await page.locator('[data-test=theme-toggle]').click()
  await expect(page.locator('html')).toHaveClass(/dark/)
  await page.setViewportSize({ width: 390, height: 844 })
  await page.reload()
  await expect(page.locator('.aside')).toHaveCount(0) // sidebar collapses into a drawer
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
  expect(overflow).toBeLessThanOrEqual(1)
})

test('打卡与会议室冲突提示', async ({ page }) => {
  await login(page, 'yui')
  await page.locator('[data-test=menu-attendance]').click()
  await page.locator('[data-test=punch-now]').click()
  await expect(page.locator('[data-test=punch-result]')).toContainText('打卡成功')
  await page.locator('[data-test=punch-now]').click()
  await expect(page.locator('[data-test=punch-result]')).toContainText('重复打卡已忽略')
  // two bookings for the same slot: second one shows a conflict error from the backend
  const day = ymd(mondayAhead(1))
  const book = (subject: string) => page.evaluate(async ([d, s]) => {
    const rooms = await (await fetch('/api/meeting/rooms', { headers: { Authorization: `Bearer ${localStorage.getItem('doe_token')}` } })).json()
    const r = await fetch('/api/meeting/bookings', { method: 'POST', headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${localStorage.getItem('doe_token')}` },
      body: JSON.stringify({ room_id: rooms[0].id, subject: s, start_at: `${d}T10:00:00`, end_at: `${d}T11:00:00` }) })
    return r.status
  }, [day, subject])
  expect(await book('排练')).toBe(201)
  await page.locator('[data-test=menu-meeting]').click()
  await page.locator('[data-test=new-booking]').click()
  const dlg = page.locator('[data-test=booking-dialog]')
  await field(dlg, 'booking-day').fill(day)
  await field(dlg, 'booking-day').press('Enter')
  await expect(dlg).toContainText('排练')
  await pickOption(page, dlg.locator('[data-test=booking-start] .el-select'), /^10:30$/)
  await pickOption(page, dlg.locator('[data-test=booking-end] .el-select'), /^11:30$/)
  await field(dlg, 'booking-subject').fill('冲突测试')
  await dlg.locator('[data-test=booking-save]').click()
  await expect(page.locator('.el-message--error').last()).toContainText('已被预约')
})
