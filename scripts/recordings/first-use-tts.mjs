// Pin the working Edge client without changing the user's global installation.
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import os from 'node:os';
const skill = process.env.RECORDER_SKILL || path.join(os.homedir(), '.codex/skills/repo-demo-recorder');
let source = await readFile(path.join(skill, 'scripts/add-tts-narration.mjs'), 'utf8');
const pattern = /await run\("uvx", \[\s*"edge-tts",/g;
if ([...source.matchAll(pattern)].length !== 1) throw new Error('Recorder changed; review the Edge adapter');
source = source.replace(pattern, 'await run("uvx", ["--from", "edge-tts==7.3.1", "edge-tts",');
const runtime = path.resolve('docs/recordings/first-use-build/add-tts-runtime.mjs');
await mkdir(path.dirname(runtime), { recursive: true });
await writeFile(runtime, source);
const result = spawnSync(process.execPath, [runtime, ...process.argv.slice(2)], { stdio: 'inherit' });
process.exit(result.status ?? 1);
