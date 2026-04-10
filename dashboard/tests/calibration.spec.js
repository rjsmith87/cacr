import { test, expect } from '@playwright/test'

test.describe('Calibration Explorer', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/calibration')
    await page.waitForSelector('.recharts-wrapper', { timeout: 20_000 })
  })

  test('scatter plot renders', async ({ page }) => {
    await expect(page.locator('h2')).toContainText('Calibration Explorer')
    const scatters = await page.locator('.recharts-scatter').count()
    expect(scatters).toBeGreaterThanOrEqual(2)
  })

  test('legend shows model names', async ({ page }) => {
    const legend = page.locator('.recharts-legend-wrapper')
    await expect(legend).toBeVisible()
    await expect(legend).toContainText('Perfect Calibration')
  })

  test('ELI5 panel loads', async ({ page }) => {
    await expect(page.locator('text=What does this mean?')).toBeVisible({ timeout: 5000 })
  })
})
