import { test, expect, type Page } from '@playwright/test';

const originalSurvey = {
    title: 'Preserved title',
    showProgressBar: 'top',
    pages: [
        { name: 'first', title: 'First page', elements: [{ type: 'text', name: 'q1', title: 'Original question', isRequired: true }] },
        { name: 'second', elements: [{ type: 'text', name: 'q2', title: 'Second page question' }] },
    ],
};

async function mockApi(page: Page) {
    await page.addInitScript(() => localStorage.setItem('i18nextLng', 'en'));
    await page.route('**/api/**', async route => {
        const path = new URL(route.request().url()).pathname;
        let data: unknown = [];
        if (path === '/api/surveys') data = [{ id: 'survey-1', name: 'Regression survey', data: originalSurvey }];
        if (path === '/api/account') data = { id: 'account', balance: 100 };
        if (path === '/api/experiments/replay-test') data = {
            id: 'replay-test', name: 'Replay regression', status: 2, curDay: 0, curT: 1,
            numDay: 1, inputTokens: 10, outputTokens: 5, config: '{}',
        };
        if (path.endsWith('/timeline')) data = [{ day: 0, t: 0 }, { day: 0, t: 1 }];
        if (path.endsWith('/metrics')) data = { happiness: [{ key: 'happiness', step: 0, value: 1 }, { key: 'happiness', step: 1, value: 2 }] };
        await route.fulfill({ json: { data, success: true, skills: [], total: 0 } });
    });
    // A local style exercises the actual Mapbox worker without a remote service/token.
    await page.route('https://api.mapbox.com/**', route => route.fulfill({
        json: { version: 8, sources: {}, layers: [{ id: 'background', type: 'background', paint: { 'background-color': '#f0f0f0' } }] },
    }));
    await page.route('https://events.mapbox.com/**', route => route.fulfill({ json: {} }));
}

for (const path of ['/agents', '/profiles', '/agent-templates', '/llms', '/workflows', '/maps', '/bill', '/skills', '/survey']) {
    test(`production route ${path} renders without runtime errors`, async ({ page }) => {
        const errors: string[] = [];
        page.on('pageerror', error => errors.push(error.message));
        await mockApi(page);
        await page.goto(path);
        await expect(page.locator('.ant-table')).toBeVisible();
        await expect(page.getByText('Unexpected Application Error!')).toHaveCount(0);
        expect(errors).toEqual([]);
    });
}

test('editing a survey preserves metadata and later pages, and switching records refreshes the builder', async ({ page }) => {
    await mockApi(page);
    let saved: { data?: typeof originalSurvey } | undefined;
    await page.route('**/api/surveys/survey-1', async route => {
        saved = route.request().postDataJSON();
        await route.fulfill({ json: { data: saved } });
    });
    await page.goto('/survey');
    await page.getByRole('button', { name: 'Edit', exact: true }).click();
    await expect(page.getByText('Original question', { exact: true })).toBeVisible();
    const dialog = page.getByRole('dialog');
    await dialog.getByRole('button', { name: /Add Question/ }).click();
    const questionDialog = page.getByRole('dialog').last();
    await questionDialog.getByLabel('Question Title').fill('Added question');
    await questionDialog.getByLabel('Question Type').click();
    await page.getByText('Text Input', { exact: true }).last().click();
    await questionDialog.getByRole('button', { name: /Add Question/ }).click();
    await expect(page.getByText('Added question', { exact: true })).toBeVisible();
    await page.getByRole('button', { name: 'Submit', exact: true }).click();
    await expect.poll(() => saved).toBeTruthy();
    expect(saved?.data?.title).toBe(originalSurvey.title);
    expect(saved?.data?.showProgressBar).toBe('top');
    expect(saved?.data?.pages[0].title).toBe('First page');
    expect(saved?.data?.pages[0].elements[0]).toEqual(originalSurvey.pages[0].elements[0]);
    expect(saved?.data?.pages[0].elements).toHaveLength(2);
    expect(saved?.data?.pages[1]).toEqual(originalSurvey.pages[1]);
    await page.getByRole('button', { name: 'Create Survey', exact: true }).click();
    await expect(page.getByText('Original question', { exact: true })).toHaveCount(0);
    await expect(page.getByText('Added question', { exact: true })).toHaveCount(0);
});

test('replay loads map workers and plots metric lines from the production chunks', async ({ page }) => {
    const errors: string[] = [];
    const missing: string[] = [];
    page.on('pageerror', error => errors.push(error.message));
    page.on('response', response => {
        if (response.status() >= 400) missing.push(`${response.status()} ${new URL(response.url()).pathname}`);
    });
    await mockApi(page);
    await page.goto('/exp/replay-test');
    await expect(page.locator('.mapboxgl-canvas')).toBeVisible();
    await page.getByRole('tab', { name: /Metrics/i }).click();
    await expect(page.locator('.js-plotly-plot .scatterlayer .js-line')).toBeVisible();
    await expect(page.locator('.js-plotly-plot .scatterlayer .point')).toHaveCount(2);
    expect(errors).toEqual([]);
    expect(missing).toEqual([]);
});

test('a late list response cannot overwrite data loaded after a language change', async ({ page }) => {
    await mockApi(page);
    let calls = 0;
    let releaseFirst!: () => void;
    const firstPending = new Promise<void>(resolve => { releaseFirst = resolve; });
    await page.route('**/api/agent-profiles', async route => {
        const call = ++calls;
        if (call === 1) await firstPending;
        await route.fulfill({ json: { data: [{ id: String(call), name: call === 1 ? 'Stale profile' : 'Current profile' }] } });
    });
    await page.goto('/profiles');
    await expect.poll(() => calls).toBe(1);
    await page.getByRole('button', { name: '中文', exact: true }).click();
    await expect(page.getByText('Current profile', { exact: true })).toBeVisible();
    const lateResponse = page.waitForResponse('**/api/agent-profiles');
    releaseFirst();
    await lateResponse;
    // Let React process both the response and its queued render.
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    await expect(page.getByText('Current profile', { exact: true })).toBeVisible();
    await expect(page.getByText('Stale profile', { exact: true })).toHaveCount(0);
    expect(calls).toBe(2);
});

test('selecting a map agent opens the lazily loaded survey preview', async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', error => errors.push(error.message));
    await mockApi(page);
    await page.route('**/api/experiments/replay-test/agents/**', async route => {
        const path = new URL(route.request().url()).pathname;
        let data: unknown = [];
        if (path.endsWith('/profile')) data = [{ id: 1, name: 'Preview agent', profile: {} }];
        if (path.endsWith('/status')) data = [{ id: 1, day: 0, t: 1, lng: 116.39124329043085, lat: 39.906120097057055, parent_id: 0, action: 'Idle', status: {} }];
        if (path.endsWith('/survey')) data = [{ id: 1, day: 0, t: 1, survey_id: 'survey-1', result: {} }];
        await route.fulfill({ json: { data } });
    });
    await page.goto('/exp/replay-test');
    const canvas = page.locator('#deckgl-overlay');
    await expect(canvas).toBeVisible();
    await expect(async () => {
        const bounds = await canvas.boundingBox();
        expect(bounds).not.toBeNull();
        await page.mouse.click(bounds!.x + bounds!.width / 2, bounds!.y + bounds!.height / 2);
        await expect(page.getByText('Preview agent', { exact: true })).toBeVisible();
    }).toPass({ timeout: 10_000 });
    await page.getByRole('tab', { name: /Survey/i }).click();
    await page.getByRole('button', { name: /Preview/i }).click();
    await expect(page.getByRole('dialog').getByText('Original question', { exact: true })).toBeVisible();
    expect(errors).toEqual([]);
});
