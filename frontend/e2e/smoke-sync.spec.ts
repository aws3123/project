import { test, expect } from '@playwright/test'

test('sync review page smoke', async ({ page }) => {
  await page.goto('/')
  await expect(page.getByRole('heading', { name: '提交 PR 进行审查' })).toBeVisible()
  await expect(page.getByRole('button', { name: '提交审查' })).toBeVisible()
})
