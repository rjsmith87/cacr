import { test, expect } from '@playwright/test'

test.describe('Capability Matrix', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/')
    await page.waitForSelector('table', { timeout: 20_000 })
  })

  test('loads without error', async ({ page }) => {
    await expect(page.locator('h2')).toContainText('Capability Matrix')
    await expect(page.locator('text=Failed to load data')).not.toBeVisible()
  })

  test('heatmap renders with 3 task rows and 4 model columns', async ({ page }) => {
    await expect(page.locator('tbody tr')).toHaveCount(3)
    // 1 task label column + 4 model columns = 5
    await expect(page.locator('thead th')).toHaveCount(5)
  })

  test('tooltip appears on cell hover', async ({ page }) => {
    const firstCell = page.locator('tbody tr:first-child td:nth-child(2) div').first()
    await firstCell.hover()

    const tooltip = page.locator('.fixed.z-\\[9999\\]')
    await expect(tooltip).toBeVisible({ timeout: 3000 })
    await expect(tooltip).toContainText('Score')
  })

  test('ELI5 panel loads', async ({ page }) => {
    await expect(page.locator('text=What does this mean?')).toBeVisible({ timeout: 5000 })
  })

  test('color legend is visible', async ({ page }) => {
    // The legend bar container with gradient
    const legendBar = page.locator('.flex.h-3.w-48')
    await expect(legendBar).toBeVisible()
  })
})
