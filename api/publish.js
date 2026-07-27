const crypto = require('crypto');

const REPO = 'peterclampton/ssbd-lake-perris';
const PATH = 'scene-layout.json';
const ALLOWED_ORIGIN = 'https://peterclampton.github.io';

function validKey(value, expected) {
  if (!value || !expected) return false;
  const a = Buffer.from(value), b = Buffer.from(expected);
  return a.length === b.length && crypto.timingSafeEqual(a, b);
}

module.exports = async (req, res) => {
  res.setHeader('Access-Control-Allow-Origin', ALLOWED_ORIGIN);
  res.setHeader('Access-Control-Allow-Headers', 'Content-Type, X-SSBD-Publish-Key');
  res.setHeader('Access-Control-Allow-Methods', 'POST, OPTIONS');
  if (req.method === 'OPTIONS') return res.status(204).end();
  if (req.method !== 'POST') return res.status(405).json({ error: 'Method not allowed' });
  if (!validKey(req.headers['x-ssbd-publish-key'], process.env.PUBLISH_KEY)) return res.status(401).json({ error: 'Unauthorized' });
  const layout = req.body && req.body.layout;
  if (!layout || !Array.isArray(layout.objects)) return res.status(400).json({ error: 'Invalid layout' });
  const token = process.env.GITHUB_TOKEN;
  if (!token) return res.status(500).json({ error: 'Server is missing GitHub configuration' });
  const headers = { Authorization: `Bearer ${token}`, Accept: 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28' };
  try {
    const current = await fetch(`https://api.github.com/repos/${REPO}/contents/${PATH}`, { headers });
    const existing = current.ok ? await current.json() : null;
    if (!current.ok && current.status !== 404) throw new Error('Could not read current layout');
    const content = Buffer.from(JSON.stringify(layout, null, 2) + '\n').toString('base64');
    const update = await fetch(`https://api.github.com/repos/${REPO}/contents/${PATH}`, {
      method: 'PUT', headers: { ...headers, 'Content-Type': 'application/json' },
      body: JSON.stringify({ message: 'Publish scene layout', content, sha: existing && existing.sha, branch: 'main' })
    });
    if (!update.ok) throw new Error('GitHub rejected the publish');
    return res.status(200).json({ ok: true });
  } catch (error) {
    return res.status(500).json({ error: error.message || 'Publish failed' });
  }
};
