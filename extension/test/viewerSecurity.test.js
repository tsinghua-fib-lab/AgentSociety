const test = require('node:test');
const assert = require('node:assert/strict');
const { load } = require('./helpers/loadSource');

test('paper and PID data are escaped in rendered HTML', () => {
  const payload = '<img src=x onerror="PWN()">';
  const { PaperArtifactViewer } = load('paperArtifactViewer.ts');
  for (const data of [{ score: payload, dimensions: { [payload]: payload } }, { blocking_issues: [payload], summary: payload }]) {
    const html = PaperArtifactViewer.renderReview(data, 'review.json', false);
    assert.ok(!html.includes(payload)); assert.ok(html.includes('&lt;img'));
  }
  assert.ok(!PaperArtifactViewer.renderFigureArgMap({ [payload]: { figure_id: payload, roles: [payload], claim_ids: [payload] } }, 'map.json', false).includes(payload));
  const { PidStatusViewer } = load('pidStatusViewer.ts');
  assert.ok(!PidStatusViewer.prototype.getWebviewContent({ pid: payload, status: payload, experiment_id: payload, start_time: payload, end_time: payload, step_count: payload, simulation_time: payload }, false).includes(payload));
});
