// Use the recorder skill's timing/padding implementation with this task's
// tested edge-tts 7.3.1 environment. Avoid the system uvx's older 7.2.8 install.
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import os from 'node:os';
const skill = process.env.RECORDER_SKILL || path.join(os.homedir(), '.codex/skills/repo-demo-recorder');
const python = process.env.RECORDING_PYTHON || path.resolve('.recording-venv/Scripts/python.exe');
let source = await readFile(path.join(skill, 'scripts/add-tts-narration.mjs'), 'utf8');
const needle = /await run\("uvx", \[\s*"edge-tts",/g;
if ([...source.matchAll(needle)].length !== 1) throw new Error('Skill source changed; review adapter');
source = source.replace(needle, `await run(${JSON.stringify(python)}, ["-m", "edge_tts",`);
source = source.replace('commandExists("uvx")', `(spawnSync(${JSON.stringify(python)}, ["-m", "edge_tts", "--version"]).status === 0)`);
const runtime = path.resolve('docs/recordings/build/add-tts-runtime.mjs');
await mkdir(path.dirname(runtime), { recursive: true });
await writeFile(runtime, source);
const result = spawnSync(process.execPath, [runtime, ...process.argv.slice(2)], { stdio: 'inherit' });
process.exit(result.status ?? 1);
