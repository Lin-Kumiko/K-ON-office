import { expect, test, type Page } from '@playwright/test'
import { expectSuccess, login, logout, pickOption, field } from './helpers'

async function approve(page: Page, user: string) {
  await login(page, user)
  await page.locator('[data-test=menu-approvals]').click()
  const row = page.locator('[data-test=task-table] .el-table__body tr').filter({ hasText: '学园祭物资' }).first()
  await row.getByRole('button', { name: '处理' }).click()
  await page.locator('[data-test=approve-btn]').click()
  await expectSuccess(page, '已通过')
  await logout(page)
}

test('费用报销：多明细精确合计 → 主管 → 财务审核 → 模拟财务确认', async ({ page }) => {
  await login(page, 'yui')
  await page.locator('[data-test=menu-expense]').click()
  await page.locator('[data-test=new-claim]').click()
  const dlg = page.locator('[data-test=claim-dialog]')
  await field(dlg, 'claim-title').fill('学园祭物资')
  const rows = dlg.locator('.el-table__body tr')
  await pickOption(page, rows.nth(0).locator('[data-test=item-category]'), '乐器与设备维护')
  await field(rows.nth(0), 'item-amount').fill('1200.10')
  await dlg.getByRole('button', { name: '添加明细' }).click()
  await pickOption(page, rows.nth(1).locator('[data-test=item-category]'), '茶点采购')
  await field(rows.nth(1), 'item-amount').fill('88.80')
  await expect(dlg.locator('[data-test=claim-total]')).toHaveText('¥1,288.90')
  await dlg.locator('[data-test=claim-submit]').click()
  await expectSuccess(page, '已提交审批')
  const row = page.locator('[data-test=claim-table] .el-table__body tr').first()
  await expect(row).toContainText('¥1,288.90')
  await expect(row).toContainText('审批中')
  await logout(page)

  await approve(page, 'mio')
  await approve(page, 'megumi')

  await login(page, 'fuuko')
  await page.locator('[data-test=menu-expense]').click()
  await page.getByRole('tab', { name: '财务处理' }).click()
  const frow = page.locator('[data-test=claim-table] .el-table__body tr').filter({ hasText: '学园祭物资' })
  await expect(frow).toContainText('已通过')
  await frow.locator('[data-test=finance-confirm]').click()
  await page.locator('.el-message-box').getByRole('button', { name: /确定|OK/ }).click()
  await expectSuccess(page, '已确认付款')
  await expect(frow).toContainText('已确认付款')
  await expect(frow).toContainText('SIM-EXP')
})
