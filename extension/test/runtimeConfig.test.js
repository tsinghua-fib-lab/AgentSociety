const test = require('node:test');
const assert = require('node:assert/strict');
const { load } = require('./helpers/loadSource');

test('both shipped env templates require replacing API key placeholders', () => {
  const { hasConfiguredLlmApiKey } = load('runtimeConfig.ts');
  for (const llmApiKey of ['', '   ', 'your_api_key', 'your-api-key-here', 'sk-your-litellm-virtual-key', 'your-litellm-api-key']) {
    assert.equal(hasConfiguredLlmApiKey({ llmApiKey }), false, llmApiKey);
  }
  assert.equal(hasConfiguredLlmApiKey({ llmApiKey: 'a-real-provider-key' }), true);
});
