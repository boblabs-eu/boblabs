/**
 * U04 — OrchestratorPage uses react-markdown, not the hand-rolled
 * `renderMarkdown` + dangerouslySetInnerHTML pipeline.
 *
 * Why source-introspection rather than a render test:
 *   react-markdown ships ESM-only at the package level and CRA's jest
 *   config doesn't transform node_modules, so a `import ReactMarkdown
 *   from 'react-markdown'` in the test file blows up with
 *   "SyntaxError: Unexpected token 'export'".
 *
 *   The audit's concern is "the hand-rolled renderer is gone". A
 *   source-level check pins that intent and fails loudly if a future
 *   commit reverts to dangerouslySetInnerHTML on the orchestrator
 *   message content.
 */

import fs from 'fs';
import path from 'path';

const orchestratorSrc = fs.readFileSync(
  path.join(__dirname, 'OrchestratorPage.js'), 'utf8',
);

describe('U04 — OrchestratorPage markdown rendering', () => {
  test('imports react-markdown', () => {
    expect(orchestratorSrc).toMatch(/^import\s+ReactMarkdown\s+from\s+['"]react-markdown['"]/m);
  });

  test('renders message content via MessageMarkdown, not dangerouslySetInnerHTML', () => {
    // The pre-fix path was `dangerouslySetInnerHTML={{ __html: renderMarkdown(...) }}`
    // on m.content + streamingText. Neither should appear now.
    expect(orchestratorSrc).not.toMatch(/dangerouslySetInnerHTML[^}]*renderMarkdown/);
    expect(orchestratorSrc).toMatch(/<MessageMarkdown>\{m\.content\}<\/MessageMarkdown>/);
    expect(orchestratorSrc).toMatch(/<MessageMarkdown>\{streamingText\s*\|\|\s*'.{1,3}'\}<\/MessageMarkdown>/);
  });

  test('exposes MessageMarkdown helper using react-markdown', () => {
    expect(orchestratorSrc).toMatch(/function MessageMarkdown/);
    expect(orchestratorSrc).toMatch(/<ReactMarkdown\b/);
  });

  test('hand-rolled renderMarkdown is gone', () => {
    // The pre-fix definition lived around line 43-58.
    expect(orchestratorSrc).not.toMatch(/^function renderMarkdown\(/m);
    expect(orchestratorSrc).not.toMatch(/\.replace\(\/&\/g, '&amp;'\)/);
  });
});
