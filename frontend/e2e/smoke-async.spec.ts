import { test, expect } from '@playwright/test'

test('async task route smoke', async ({ page }) => {
  await page.goto('/code-review/task_mock_1')
  await expect(page.getByText('代码审查 · 任务详情')).toBeVisible()
  await expect(page.getByText(/Task ID:/)).toBeVisible()
})
