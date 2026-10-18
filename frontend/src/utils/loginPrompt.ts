// One shared "please log in" dialog for anonymous visitors who try to do something.
import { ElMessageBox } from 'element-plus'
import type { Router } from 'vue-router'

let router: Router | null = null
let open = false

export function bindLoginPrompt(r: Router) {
  router = r
}

export async function promptLogin(redirect?: string) {
  if (open || !router) return
  open = true
  const target = redirect ?? router.currentRoute.value.fullPath
  try {
    await ElMessageBox.confirm('这个操作需要登录。还没有账号的话，先注册一个吧。', '请先登录', {
      confirmButtonText: '去登录',
      cancelButtonText: '去注册',
      distinguishCancelAndClose: true,
      type: 'info',
    })
    router.push({ name: 'login', query: { redirect: target } })
  } catch (action) {
    if (action === 'cancel') router.push({ name: 'register', query: { redirect: target } })
  } finally {
    open = false
  }
}
