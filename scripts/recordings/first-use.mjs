import { spawnSync } from 'node:child_process';
const phase = process.argv[2] || 'capture';
const scripts = { capture: 'capture-first-use.py', compose: 'build-first-use-video.py', guide: 'build-first-use-guide.py', finish: 'finish-first-use.py', package: 'package-first-use.py' };
if (!scripts[phase]) throw new Error('Use capture, compose, guide, finish or package');
const result = spawnSync(process.env.RECORDING_PYTHON || 'python', ['scripts/recordings/' + scripts[phase], ...process.argv.slice(3)], { stdio: 'inherit' });
process.exit(result.status ?? 1);
