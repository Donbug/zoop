import Defuddle from 'defuddle';
import { parseHTML } from 'linkedom';

// Supplied HTML only. Neither document resources nor Defuddle's async APIs may fetch.
const noNetwork = () => { throw new Error('network_disabled'); };
globalThis.fetch = noNetwork;
const chunks = [];
let size = 0;
for await (const chunk of process.stdin) {
  size += chunk.length;
  if (size > 24_000_000) throw new Error('input_limit');
  chunks.push(chunk);
}
const input = JSON.parse(Buffer.concat(chunks).toString('utf8'));
if (typeof input.html !== 'string' || typeof input.url !== 'string') throw new Error('invalid_input');
const { document } = parseHTML(input.html);
// These are the documented linkedom compatibility adjustments in Defuddle 0.19.6.
document.styleSheets ??= [];
if (document.defaultView && !document.defaultView.getComputedStyle) {
  document.defaultView.getComputedStyle = () => ({ display: '' });
}
document.URL = input.url;
const result = new Defuddle(document, { url: input.url, useAsync: false, fetch: noNetwork }).parse();
if (typeof result.content !== 'string' || Buffer.byteLength(result.content, 'utf8') > 10_000_000) {
  throw new Error('invalid_output');
}
process.stdout.write(JSON.stringify({
  content: result.content,
  profile: { parser: 'defuddle-0.19.6', dom: 'linkedom-0.18.14', representation: 'extracted-html-1' }
}));
