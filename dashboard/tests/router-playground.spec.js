import { test, expect } from '@playwright/test'

test.describe('Router Playground', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/router')
    await page.waitForSelector('textarea', { timeout: 10_000 })
  })

  test('form elements render', async ({ page }) => {
    await expect(page.locator('h2')).toContainText('Router Playground')
    await expect(page.locator('textarea')).toBeVisible()
    await expect(page.locator('select').first()).toBeVisible()
  })

  test('routes code to flash-lite with auto complexity', async ({ page }) => {
    await page.locator('textarea').fill(
      'def get_user(conn, name):\n    return conn.execute(f"SELECT * FROM users WHERE name=\'{name}\'").fetchone()'
    )
    await page.locator('select').first().selectOption('SecurityVuln')

    // Verify complexity is on Auto
    const complexitySelect = page.locator('select').nth(1)
    await expect(complexitySelect).toHaveValue('auto')

    await page.locator('button[type="submit"]').click()
    await page.waitForSelector('text=Recommended Model', { timeout: 20_000 })

    // Should recommend flash-lite (use .first() to avoid strict mode violation)
    await expect(page.getByText('gemini-2.5-flash-lite').first()).toBeVisible()

    // Complexity inferred badge
    await expect(page.getByText('Complexity inferred').first()).toBeVisible()
  })

  test('ELI5 panel appears after routing', async ({ page }) => {
    await page.locator('textarea').fill('def add(a, b): return a + b')
    await page.locator('select').first().selectOption('CodeReview')
    await page.locator('button[type="submit"]').click()
    await page.waitForSelector('text=Recommended Model', { timeout: 20_000 })

    await expect(page.locator('text=What does this mean?')).toBeVisible({ timeout: 5000 })
  })
})
