import { test, expect } from '@playwright/test'

test.describe('Pipeline Cost', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/pipeline')
    await page.waitForSelector('h2', { timeout: 20_000 })
    // Wait for data to load — cards or empty state
    await page.waitForTimeout(3000)
  })

  test('all 4 strategy cards render', async ({ page }) => {
    await expect(page.getByRole('heading', { name: 'All Haiku' })).toBeVisible({ timeout: 10_000 })
    await expect(page.getByRole('heading', { name: 'All Flash Lite' })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'All GPT-4o-mini' })).toBeVisible()
    await expect(page.getByRole('heading', { name: 'CACR Routed' })).toBeVisible()
  })

  test('cost values are present', async ({ page }) => {
    // Cards should show dollar amounts, not dashes
    const costs = await page.locator('text=/^\\$0\\./')  .count()
    expect(costs).toBeGreaterThanOrEqual(1)
  })

  test('callout banner is visible', async ({ page }) => {
    await expect(page.getByText('All three strategies achieve comparable accuracy')).toBeVisible({ timeout: 10_000 })
  })

  test('comparison table has rows', async ({ page }) => {
    const rows = await page.locator('tbody tr').count()
    expect(rows).toBeGreaterThanOrEqual(3)
  })

  test('ELI5 panel loads', async ({ page }) => {
    await expect(page.locator('text=What does this mean?')).toBeVisible({ timeout: 5000 })
  })
})
