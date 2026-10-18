import { expect, test, type Page } from '@playwright/test'
import { addDays, api, expectSuccess, login, logout, mondayAhead, pickOption, ymd, field } from './helpers'

async function drag(page: Page, from: ReturnType<Page['locator']>, to: ReturnType<Page['locator']>) {
  const a = (await from.boundingBox())!
  const b = (await to.boundingBox())!
  await page.mouse.move(a.x + a.width / 2, a.y + a.height / 2)
  await page.mouse.down()
  await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2, { steps: 8 })
  await page.mouse.up()
}

test('流程配置：设计器新增 HR 备案节点并发布 → 新出差单按新版本执行', async ({ page }) => {
  await login(page, 'ui')
  await page.goto('/workflow')
  await page.locator('[data-test=def-travel]').click()
  await page.locator('[data-test=new-draft]').click()
  await expectSuccess(page, '已创建草稿')
  // remove edge mgr -> end, insert an approval node, wire mgr -> n1 -> end
  const canvas = page.locator('[data-test=canvas]')
  await canvas.locator('[data-test=edge-e2] .hit').click({ force: true })
  await expect(page.locator('.props')).toContainText('连线属性')
  await page.locator('[data-test=delete-selected]').click()
  await page.locator('[data-test=add-approval]').click()
  const node = canvas.locator('[data-test=node-n1]')
  await expect(node).toBeVisible()
  await field(page, 'prop-name').fill('人事备案')
  await pickOption(page, page.locator('[data-test=prop-approver]'), 'HR 管理员')
  // move the new node into the visible area below the line, then connect
  const nb = (await node.boundingBox())!
  const cb = (await canvas.boundingBox())!
  await page.mouse.move(nb.x + 30, nb.y + 25)
  await page.mouse.down()
  await page.mouse.move(cb.x + 360, cb.y + 330, { steps: 8 })
  await page.mouse.up()
  const moved = (await node.boundingBox())!
  expect(moved.x + moved.width).toBeLessThan(cb.x + cb.width)
  await drag(page, canvas.locator('[data-test=port-mgr]'), node)
  await drag(page, canvas.locator('[data-test=port-n1]'), canvas.locator('[data-test=node-end]'))
  await page.locator('[data-test=validate]').click()
  await expect(page.getByText('校验通过，可以发布')).toBeVisible()
  await page.locator('[data-test=publish]').click()
  await page.locator('.el-message-box').getByRole('button', { name: /确定|OK/ }).click()
  await expectSuccess(page, '已发布')
  await expect(page.locator('[data-test=def-travel]')).toContainText('v2')
  const defs = await api(page, 'GET', '/api/workflow/definitions')
  expect(defs.body.find((d: any) => d.key === 'travel').current_version).toBe(2)
  await logout(page)

  // execute: travel now needs manager + HR
  await login(page, 'yui')
  const s = mondayAhead(3)
  const res = await api(page, 'POST', '/api/travel?submit=true', { destination: 'Live House', start_date: ymd(s),
    end_date: ymd(addDays(s, 1)), purpose: '巡演' })
  expect(res.status).toBe(201)
  const inst = await api(page, 'GET', `/api/workflow/instances/${res.body.instance_id}`)
  expect(inst.body.version).toBe(2)
  await logout(page)
  for (const u of ['mio', 'nodoka']) {
    await login(page, u)
    await page.locator('[data-test=menu-approvals]').click()
    await page.locator('[data-test=task-table] .el-table__body tr').filter({ hasText: 'Live House' }).getByRole('button', { name: '处理' }).click()
    await expect(page.locator('.el-drawer').last()).toContainText('v2')
    await page.locator('[data-test=approve-btn]').click()
    await expectSuccess(page, '已通过')
    await logout(page)
  }
  await login(page, 'yui')
  const t = await api(page, 'GET', `/api/travel/${res.body.id}`)
  expect(t.body.status).toBe('approved')
})
