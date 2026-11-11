# AgentSociety UI

[![License](https://img.shields.io/badge/License-Apache%202.0-blue)](../LICENSE)

React + TypeScript + Vite dashboard, using Ant Design, Monaco, Plotly and Mapbox/Deck.gl. User documentation: [AgentSociety 2](https://agentsociety2.readthedocs.io/).

## Develop and verify

From `frontend/`:

```bash
npm ci
npm run dev
npm run lint
npm run build

# Browser regressions against the production build (mock API responses)
npx playwright install chromium
npm run test:e2e
```

The dev server defaults to `http://localhost:5173`. The current `/api` development proxy targets `http://localhost:80`; adjust [vite.config.ts](vite.config.ts) to your API gateway. The standalone AS2 backend defaults to `127.0.0.1:8001`, with its own `/docs`. Check endpoint compatibility before pointing every dashboard route at that backend: several pages use older `/api/...` contracts, while the skill page uses `/api/v1/agent-skills/...`.

`npm run test:docs` checks the separately built bilingual documentation, including search and mobile controls. It serves `../docs-preview` by default; set `DOCS_PREVIEW_URL` to reuse a running preview. `DOCS_PYTHON_EXECUTABLE` selects the Python interpreter used for the static server; the default is `../.venv/bin/python`.

From the repository root, `make ci-frontend` runs the lint and production build used by GitHub and GitLab. Before pushing UI changes, run `make check-frontend` locally to include browser regressions. After building the documentation with `make ci-docs-build`, use `make ci-docs-browser` locally for its browser checks. These browser checks require Chromium as shown above; CI does not install or run browsers.

Browser regressions use fixtures; they verify rendering and interactions, not a live experiment. `PLAYWRIGHT_CHROMIUM_EXECUTABLE` can select a locally installed Chromium. For extension documentation assets, see [the extension development guide](../extension/docs/DEVELOPMENT.md#文档配图维护).

## 中文说明

这是 React + Vite 网页仪表盘。开发、检查、构建、浏览器回归共用上方命令，避免维护两套步骤。页面入口在 `src/pages/`，导航在 `src/Menu.tsx`，国际化资源在 `src/i18n/`。

开发代理当前转发到 `localhost:80`，请按实际 API 网关修改 `vite.config.ts`。AS2 独立后端默认是 `127.0.0.1:8001`；部分页面仍使用旧版接口，不能仅改端口就假定所有页面都兼容。浏览器测试使用固定数据，不代表真实实验结果。工作台配图的维护规则见[扩展开发指南](../extension/docs/DEVELOPMENT.md#文档配图维护)。

## Dependency maintenance

Keep `@deck.gl/widgets` and `rc-field-form`: DeckGL and Pro Components import them during bundling even though application code does not. Verify removals with `npm ci` and a production build, then run the browser tests. Plotly's React type declarations belong to development dependencies.

For documentation-only checks, install the lightweight workspace with `npm ci --workspace tests/docs --include-workspace-root=false`, then run `npm run test:docs`. It shares the frontend lockfile; the dashboard build still uses the full `npm ci`.
