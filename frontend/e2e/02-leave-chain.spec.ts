import { expect, test, type Page } from '@playwright/test'
import { addDays, expectSuccess, fillDate, login, logout, mondayAhead, pickOption, ymd, field } from './helpers'

async function approveFirst(page: Page, titlePart: string) {
  await page.locator('[data-test=menu-approvals]').click()
  const row = page.locator('[data-test=task-table] .el-table__body tr').filter({ hasText: titlePart }).first()
  await expect(row).toBeVisible()
  await row.getByRole('button', { name: '处理' }).click()
  await field(page, 'approve-comment').fill('同意，合宿加油')
  await page.locator('[data-test=approve-btn]').click()
  await expectSuccess(page, '已通过')
  await page.keyboard.press('Escape')
}

test('员工请假 → 主管审批 → HR 审核 → 结果与余额', async ({ page }) => {
  const start = mondayAhead(2)
  const end = addDays(start, 3) // Mon-Thu = 4 days > 3 -> HR review
  await login(page, 'yui')
  await page.locator('[data-test=menu-leave]').click()
  await expect(page.locator('[data-test=balance-annual]')).toContainText('5 天')
  await page.locator('[data-test=new-leave]').click()
  const dlg = page.locator('[data-test=leave-dialog]')
  await pickOption(page, dlg.locator('[data-test=leave-type]'), '年假')
  await fillDate(field(dlg, 'leave-start'), ymd(start))
  await fillDate(field(dlg, 'leave-end'), ymd(end))
  await expect(dlg.locator('[data-test=leave-calc]')).toContainText('4 天')
  await field(dlg, 'leave-reason').fill('去琴吹家别墅合宿练习')
  await dlg.locator('[data-test=leave-submit]').click()
  await expectSuccess(page, '已提交审批')
  await expect(page.locator('[data-test=leave-table]')).toContainText('审批中')
  await expect(page.locator('[data-test=balance-annual]')).toContainText('1 天') // 4 days frozen
  await logout(page)

  await login(page, 'mio')
  await approveFirst(page, '平泽唯的年假申请')
  await logout(page)

  await login(page, 'himeko')
  await approveFirst(page, '平泽唯的年假申请')
  await logout(page)

  await login(page, 'yui')
  await page.locator('[data-test=menu-leave]').click()
  await expect(page.locator('[data-test=leave-table] .el-table__body tr').first()).toContainText('已通过')
  await expect(page.locator('[data-test=balance-annual]')).toContainText('已用 4 天')
  await page.getByRole('button', { name: '审批进度' }).first().click()
  const drawer = page.locator('.el-drawer').last()
  await expect(drawer).toContainText('流程结束（通过）')
  await expect(drawer).toContainText('人事审核')
})
