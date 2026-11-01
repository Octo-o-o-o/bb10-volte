// Windows FFmpeg has no image glob support. Keep the skill's gates and sample
// times, replacing only contact-sheet input enumeration with a concat list.
import { readFile, writeFile, mkdir } from 'node:fs/promises';
import { spawnSync } from 'node:child_process';
import path from 'node:path';
import os from 'node:os';
const skill = process.env.RECORDER_SKILL || path.join(os.homedir(), '.codex/skills/repo-demo-recorder');
let source = await readFile(path.join(skill, 'scripts/validate-recording-report.mjs'), 'utf8');
const start = source.indexOf('    runFfmpeg([\n      "-y",\n      "-pattern_type"');
const end = source.indexOf('\n  }\n\n  const review =', start);
if (start < 0 || end < 0) throw new Error('Recorder changed; review the Windows contact-sheet adapter');
const replacement = `    const inputs = path.join(outputDir, "contact-inputs.txt")
    await writeFile(inputs, selectedSamples.map(sample => "file '" + sample.file.replace(/\\\\/g, "/").replace(/'/g, "'\\\\''") + "'").join("\\n"))
    try {
      runFfmpeg(["-y", "-f", "concat", "-safe", "0", "-i", inputs,
        "-vf", \`scale=360:-1,tile=\${columns}x\${rows}:padding=8:margin=8:color=white\`,
        "-frames:v", "1", contactSheet])
    } finally { await (await import("node:fs/promises")).unlink(inputs) }`;
source = source.slice(0, start) + replacement + source.slice(end);
const runtime = path.resolve('docs/recordings/first-use-build/validate-runtime.mjs');
await mkdir(path.dirname(runtime), { recursive: true });
await writeFile(runtime, source);
const result = spawnSync(process.execPath, [runtime, ...process.argv.slice(2)], { stdio: 'inherit' });
process.exit(result.status ?? 1);
