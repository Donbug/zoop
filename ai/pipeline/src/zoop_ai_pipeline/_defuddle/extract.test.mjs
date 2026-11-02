import assert from 'node:assert/strict';
import { spawnSync } from 'node:child_process';
import { test } from 'node:test';

const helper = new URL('./extract.mjs', import.meta.url);
function extract(html) {
  return spawnSync(process.execPath, [helper.pathname], {
    input: JSON.stringify({ html, url: 'https://news.example/article' }),
    encoding: 'utf8', timeout: 30_000,
    env: { PATH: process.env.PATH },
  });
}

test('real pinned defuddle extracts supplied HTML without remote services or scripts', () => {
  const paragraph = '한글 😀 e\u0301 quarterly report with detailed operating results and financial disclosure. ';
  const result = extract(`<html><head><title>Quarterly results</title></head><body>
    <nav>UNRELATED NAVIGATION</nav><main><h1>Quarterly results</h1>
    <p>${paragraph.repeat(12)}</p><p>Second source paragraph remains here for exact retained output.</p>
    <pre><code>print('\\{값\\}')</code></pre><a href="https://news.example/source">Source link</a>
    </main><script>throw new Error('PAGE_SCRIPT_MUST_NOT_EXECUTE')</script>
    <img src="http://127.0.0.1/private-resource"></body></html>`);
  assert.equal(result.status, 0, result.stderr);
  const output = JSON.parse(result.stdout);
  assert.deepEqual(output.profile, { parser: 'defuddle-0.19.6', dom: 'linkedom-0.18.14', representation: 'extracted-html-1' });
  assert.ok(output.content.includes('한글 😀 e\u0301'));
  assert.ok(output.content.includes('\\{값\\}'));
  assert.ok(output.content.includes('https://news.example/source'));
  assert.ok(!output.content.includes('PAGE_SCRIPT_MUST_NOT_EXECUTE'));
  assert.ok(!output.content.includes('UNRELATED NAVIGATION'));
});

test('malformed JSON is refused rather than turned into an article', () => {
  const result = spawnSync(process.execPath, [helper.pathname], { input: '{invalid', encoding: 'utf8' });
  assert.notEqual(result.status, 0);
  assert.equal(result.stdout, '');
});
