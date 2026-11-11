import { defineConfig } from '@playwright/test';

const externalPreview = process.env.DOCS_PREVIEW_URL;
const previewPython = process.env.DOCS_PYTHON_EXECUTABLE || '../.venv/bin/python';

export default defineConfig({
    testDir: './tests/docs',
    workers: 1,
    retries: 0,
    globalTimeout: 120_000,
    use: {
        baseURL: externalPreview || 'http://127.0.0.1:4174',
        trace: 'retain-on-failure',
        launchOptions: { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE },
    },
    webServer: externalPreview ? undefined : {
        command: `${previewPython} -m http.server 4174 --bind 127.0.0.1 --directory ../docs-preview`,
        url: 'http://127.0.0.1:4174/zh/index.html',
        reuseExistingServer: false,
    },
});
