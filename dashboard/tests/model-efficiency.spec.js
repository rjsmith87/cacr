import { test, expect } from '@playwright/test'

test.describe('Model Efficiency', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/efficiency')
    await page.waitForSelector('.recharts-wrapper', { timeout: 20_000 })
  })

  test('bar chart renders', async ({ page }) => {
    await expect(page.locator('h2')).toContainText('Model Efficiency')
    const bars = await page.locator('.recharts-bar').count()
    expect(bars).toBeGreaterThanOrEqual(1)
  })

  test('legend shows model names', async ({ page }) => {
    const legend = page.locator('.recharts-legend-wrapper')
    await expect(legend).toBeVisible()
  })

  test('summary cards render for each model', async ({ page }) => {
    const cards = await page.locator('text=avg score/cost ratio').count()
    expect(cards).toBeGreaterThanOrEqual(3)
  })

  test('ELI5 panel loads', async ({ page }) => {
    await expect(page.locator('text=What does this mean?')).toBeVisible({ timeout: 5000 })
  })
})
