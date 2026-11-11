import { test, expect } from '@playwright/test';

for (const [language, query, resultTitle] of [
    ['zh', '数据集', '数据集与输入数据'],
    ['en', 'dataset', 'Datasets and input data'],
]) {
    test(`${language} search finds the dataset guide`, async ({ page }) => {
        await page.goto(`/${language}/search.html?q=${encodeURIComponent(query)}`);
        await expect(page.locator('#search-results').getByRole('link', { name: resultTitle, exact: true })).toBeVisible();
    });

    test(`${language} mobile navigation, theme and code copy work`, async ({ page, context }) => {
        const errors: string[] = [];
        page.on('pageerror', error => errors.push(error.message));
        await context.grantPermissions(['clipboard-read', 'clipboard-write']);
        await page.setViewportSize({ width: 390, height: 900 });
        await page.goto(`/${language}/index.html`);
        const navigation = page.locator('.nav-overlay-icon');
        await navigation.focus();
        await page.keyboard.press('Space');
        await expect(navigation).toHaveAttribute('aria-expanded', 'true');
        await page.keyboard.press('Enter');
        await expect(navigation).toHaveAttribute('aria-expanded', 'false');
        const theme = page.locator('.theme-toggle:visible').first();
        const original = await page.locator('body').getAttribute('data-theme');
        await theme.click();
        await expect(page.locator('body')).not.toHaveAttribute('data-theme', original || 'auto');
        const chosen = await page.locator('body').getAttribute('data-theme');
        await page.reload();
        await expect(page.locator('body')).toHaveAttribute('data-theme', chosen || 'auto');
        const code = page.locator('.highlight-bash').first();
        await code.hover();
        await code.locator('button.copybtn').click();
        await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toBe('pip install agentsociety2');
        const card = page.locator('.start-links .sd-card').first();
        await card.click();
        await expect(page).toHaveURL(new RegExp(`/${language}/user_guide\\.html$`));
        expect(errors).toEqual([]);
    });

    test(`${language} task guides link correctly and the API index fits tablet width`, async ({ page }) => {
        for (const guide of ['agents', 'env_modules', 'agent_skills', 'skills']) {
            await page.goto(`/${language}/${guide}.html`);
            const cards = page.locator('.topic-links .sd-card');
            await expect(cards).toHaveCount(3);
            const first = cards.first().locator('a').first();
            const destination = await first.getAttribute('href');
            expect(destination).toBeTruthy();
            const response = await page.goto(new URL(destination!, page.url()).href);
            expect(response?.status()).toBe(200);
            await expect(page.locator('article h1')).toBeVisible();
        }
        await page.setViewportSize({ width: 1024, height: 900 });
        await page.goto(`/${language}/genindex.html`);
        expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1)).toBe(false);
    });
}
