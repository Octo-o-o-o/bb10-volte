import { readFile, writeFile, mkdir } from 'node:fs/promises';
import path from 'node:path';

export const operators = {
  mobile: { zh: '移动 460-00', en: 'Mobile 460-00' },
  unicom: { zh: '联通 460-01', en: 'Unicom 460-01' },
  telecom: { zh: '电信 460-11', en: 'Telecom 460-11' },
};
const states = {
  automatic_supported: { zh: '自动适配', en: 'Automatic' },
  manual_candidate: { zh: '手动候选', en: 'Manual trial' },
  read_only_lifecycle_pending: { zh: '只读诊断', en: 'Read-only' },
  blocked: { zh: '暂未开放', en: 'Not open' },
};
const families = { q10: 'Q10', classic: 'Q20 / Classic', passport: 'Passport / Q30' };
const escape = value => String(value).replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;').replaceAll('"', '&quot;');
const isCandidate = model => Object.values(model.routes).some(route => ['manual_candidate', 'read_only_lifecycle_pending'].includes(route));
const readonly = model => Object.values(model.routes).includes('read_only_lifecycle_pending');

export function instructions(model, language) {
  const en = language === 'en';
  const readOnly = readonly(model);
  const carrier = Object.entries(model.routes).filter(([, route]) => ['manual_candidate', 'read_only_lifecycle_pending'].includes(route))
    .map(([operator]) => operators[operator][language]).join(en ? ', ' : '、');
  const title = en ? `BB10 VoLTE r15 — ${model.variant} testing instructions` : `BB10 VoLTE r15｜${model.variant} 测试说明`;
  const mode = en ? (readOnly ? 'READ-ONLY DIAGNOSTICS. Do not install or start.' : 'MANUAL CANDIDATE. No hardware acceptance yet; autostart stays off.')
    : (readOnly ? '本机型仅开放只读诊断，不进行安装或启动。' : '本机型为手动候选，尚未真机验收，自启动始终关闭。');
  const prerequisite = en ? [
    `For ${families[model.family]} ${model.variant} only. Carriers: ${carrier}.`,
    model.note.en,
    'Before starting: confirm the exact suffix in Settings > About, OS 10.3.3.3216, existing working AutoRoot v4 / Root SSH, a provisioned USIM without ISIM, and working LTE mobile data with Wi-Fi off. The app checks SIM type, home PLMN and six native-file hashes; do not collect system files yourself.',
    'Use a phone with a backup and a clean, restorable baseline. If Root/SSH is unavailable, stop and report that fact; do not wipe or flash just to provide a report. If the automatic service, a mobile-app transaction or another installer already manages the phone, stop and preserve that state. Desktop and mobile tools must not write at the same time.',
    'Download the r15 Windows EXE or Mac DMG from https://bb10-volte.octoooo.com/en/index.html#download and verify SHA-256 using https://bb10-volte.octoooo.com/en/guide.html#verify . Keep the same package, SIM and selected carrier for the whole test. The trial does not fix missing LTE coverage or change radio attachment policy.',
  ] : [
    `仅适用于 ${families[model.family]} ${model.variant}。本批运营商：${carrier}。`,
    model.note.zh,
    '开始前：在手机“设置 → 关于”确认完整后缀；系统须为 10.3.3.3216，已有有效 AutoRoot v4 / Root SSH，USIM 已开通 VoLTE 且无 ISIM。关闭 Wi-Fi 后，手机应已有可用的 LTE 移动数据。SIM 类型、归属网络和六个原生文件版本由程序检查，无需自行寻找系统文件。',
    '先备份，并确认手机处于可恢复的干净状态。没有 Root 或 SSH 时先停止并反馈，不要为了提交报告清空重刷。如果手机正在由三网自动服务、手机版事务或其他安装器管理，请保留现状，不要覆盖。桌面和手机版不能同时写入。',
    '从 https://bb10-volte.octoooo.com/index.html#download 下载 r15 Windows EXE 或 Mac DMG，按 https://bb10-volte.octoooo.com/guide.html#verify 核对 SHA-256。整个测试使用同一安装包、同一张卡和同一运营商。本试测不会修复当地没有 LTE 覆盖的问题，也不修改基带入网策略。',
  ];
  const steps = en ? (readOnly ? [
    `1. Open More > Local candidate variant trials. Select ${model.variant} and the actual carrier, then Check this phone. Do not opt into experimental use.`,
    '2. Inspect the results only. A stop/restoration-not-validated block is expected for this Passport suffix, even if native hashes pass. Do not install, start, enable autostart, disable/restore, flash, or run the manual candidate call/SMS test below another model.',
    '3. Use More > Export check report to save JSON, and Problem / Feedback to preview and save the redacted ZIP. Keep the reported model/board, OS, native-file hash summary, LTE/SIM checks and exact blocking reason. The app collects those fields automatically.',
    '4. Send the files and completed form below. Installation, calls, SMS and restoration are N/A (read-only), not failures or passes. If SSH fails, submit the computer OS, package filename, connection stage and redacted error instead.',
  ] : [
    `1. Open More > Local candidate variant trials. Select ${model.variant} and the actual carrier, then Check this phone. Leave experimental consent off for this first check; export the initial JSON report.`,
    '2. Read every blocking item. Only when technical checks pass and experimental consent is the remaining requirement, explicitly opt into experimental use and recheck. Confirm the backup, provisioned VoLTE and no active call. Unknown files, wrong suffix/SIM, missing LTE or an uncertain existing installation mean stop and report; do not edit profiles or borrow another model’s image.',
    '3. Click Install and verify and wait for readback. This installs only. Then click Start and verify separately. Keep autostart off. If either step fails, preserve reports and stop; do not keep reinstalling. IMS registration alone is not call acceptance.',
    '4. With a second phone and the native dialer, test one outgoing and one incoming call, about 30–60 seconds each. Record actual duration, audio in both directions and whether LTE remains throughout each call.',
    '5. Using ordinary SMS, receive one short message, one long message spanning at least two SMS segments, then two separately sent messages with identical content. Send one message from the BlackBerry too. Record counts and whether any duplicate arrives during at least three minutes of observation. Do not include message text or numbers in the report.',
    '6. Choose More > Disable and restore. Wait for confirmed restoration, then restart normally; check that LTE data returns and the trial does not autostart. If restoration fails or the state is unclear, preserve reports and stop rather than repeating installation or restoration. Do not hot-swap the SIM.',
    '7. Export the check report after the attempt and after restoration. Use Problem / Feedback to preview and save the ZIP. Send these files with the form below. Mark anything not performed as not tested; an app success code does not fill in real call or SMS results.',
  ]) : (readOnly ? [
    `1. 打开“更多 → 候选机型本地试测”，选择 ${model.variant} 和实际运营商，点击“检查本机条件”。不要勾选实验试用。`,
    '2. 只阅读检查结果。这个 Passport 后缀即使六文件匹配，也会因“停止与恢复未验证”被阻断，这是当前预期。不要安装、启动、开启自启动、停用恢复或刷机，也不要套用其他型号的手动通话/短信试测步骤。',
    '3. 通过“更多 → 导出检查报告”保存 JSON，再用“遇到问题 / 反馈”预览并保存脱敏 ZIP。报告需保留识别到的型号/主板、系统、六文件校验摘要、LTE/SIM 检查和具体阻断原因；这些由程序自动采集。',
    '4. 将报告和下方表格反馈。安装、通话、短信和恢复填写“不适用（只读）”，不能标成失败或已通过。若 SSH 根本连不上，提供电脑系统、安装包文件名、卡住步骤和脱敏后的错误提示即可。',
  ] : [
    `1. 打开“更多 → 候选机型本地试测”，选择 ${model.variant} 和实际运营商，点击“检查本机条件”。第一次先不勾选实验试用，保存初次检查 JSON。`,
    '2. 逐项阅读阻断原因。只有技术检查均满足、只剩实验同意待确认时，再明确勾选实验试用并重新检查，确认已备份、SIM 已开通 VoLTE、当前无通话。未知文件、型号/SIM 不符、没有 LTE 或已有安装状态不明时，停止并反馈，不改配置绕过，也不套用其他型号镜像。',
    '3. 点击“安装并验证”，等待安装回读完成；然后单独点击“启动并验证”，保持自启动关闭。任一步失败都先保留报告并停止，不要反复覆盖安装。IMS 注册成功仅表示可以开始实测，不能算通话通过。',
    '4. 使用手机系统拨号器和另一台电话，各测试一次呼出、一次呼入，每次约 30–60 秒。分别记录实际时长、双方能否听见，以及通话全程是否保持 LTE。',
    '5. 使用普通短信：让对方发一条短短信、一条至少分两段的长短信，再分别发两条内容相同的独立短信；本机也发一条给对方。记录实际收到的条数，并继续观察至少 3 分钟是否重复。不要反馈短信内容或电话号码。',
    '6. 点击“更多 → 停用并恢复”，等程序确认恢复完成后再正常重启；确认 LTE 数据恢复、试测服务没有自动启动。恢复失败或状态不明时保留报告并停止，不重复安装或恢复。不要热插拔换卡。',
    '7. 保存试测后、恢复后的检查 JSON，并通过“遇到问题 / 反馈”预览和保存 ZIP，附上下方结果表。没有做的项目填“未测试”，不能用注册成功或程序提示代填通话、短信成功。',
  ]);
  const template = en ? [
    'FEEDBACK FORM (fill in observations)', `Exact variant: ${model.variant}`, `Carrier / home PLMN: [choose from ${carrier}]`,
    'City / test date and time (no street address):', 'Computer OS and architecture / application package filename:',
    'BB10 OS version / Root SSH available: yes / no / unknown', 'LTE mobile data before the test: works / fails / not tested',
    'SIM type / native-file checks: from the report; unknown if unavailable', 'Current stage / expected result / actual result / exact error:',
    ...(readOnly ? ['Install / start / calls / SMS / restore / reboot: N/A (read-only)'] : [
      'Install / separate manual start: pass / fail / not tested (each)',
      'Outgoing / incoming: connected? duration? two-way audio? LTE throughout? (each)',
      'Short SMS / long SMS / two identical separate SMS: received counts; later duplicate yes/no/not tested',
      'SMS send / observation time in minutes:', 'Disable and restore / LTE after normal reboot / autostart stayed off: pass / fail / not tested (each)',
    ]),
    'Attachments: initial and final check JSON, feedback ZIP, redacted error screenshot if useful; use filenames/feedback ID.',
    'Review files before sending them to the maintainer who invited you. Do not send SSH configuration, keys, passwords, phone backups, raw communication logs, phone numbers, IMSI, IMEI, ICCID, PIN or SMS contents. Feedback is saved locally and is not uploaded automatically.',
    `Instructions: https://bb10-volte.octoooo.com/en/trials.html#${model.variant.toLowerCase()}`,
  ] : [
    '反馈表（请填写真实观察）', `完整型号：${model.variant}`, `运营商 / 归属 PLMN：[从 ${carrier} 中选择]`,
    '所在城市 / 测试日期时间（不需要具体地址）：', '电脑系统及架构 / 应用安装包文件名：',
    'BB10 系统版本 / Root SSH 是否可用：是 / 否 / 不清楚', '试测前 LTE 移动数据：可用 / 不可用 / 未测试',
    'SIM 类型 / 六文件检查：以程序报告为准，无法取得填“不清楚”', '卡在哪一步 / 预期结果 / 实际现象 / 完整错误提示：',
    ...(readOnly ? ['安装 / 启动 / 通话 / 短信 / 恢复 / 重启：不适用（只读）'] : [
      '安装 / 单独手动启动：分别填 通过 / 失败 / 未测试',
      '呼出 / 呼入：分别填是否接通、实际时长、双向声音、是否全程 LTE',
      '短短信 / 长短信 / 同内容两条独立短信：分别填收到条数、之后是否重复',
      '短信发送结果 / 重复观察时长（分钟）：', '停用恢复 / 正常重启后 LTE / 是否保持不自启：分别填 通过 / 失败 / 未测试',
    ]),
    '附件：初次和最终检查 JSON、反馈 ZIP；必要时附已遮挡隐私的错误截图。写明文件名或反馈 ID。',
    '发送前检查附件，再发给邀请你测试的维护者。不要发送 SSH 配置、私钥、密码、手机备份、原始通信日志、手机号、IMSI、IMEI、ICCID、PIN 或短信内容。反馈只保存在本地，程序不自动上传。',
    `对应说明：https://bb10-volte.octoooo.com/trials.html#${model.variant.toLowerCase()}`,
  ];
  return [title, mode, ...prerequisite.filter(Boolean), en ? 'STEPS' : '操作步骤', ...steps, ...template].join('\n\n') + '\n';
}

function matrix(data, language) {
  const en = language === 'en';
  const rows = data.models.map(model => {
    const target = isCandidate(model) ? `trials.html#${model.variant.toLowerCase()}`
      : Object.values(model.routes).includes('automatic_supported') ? 'guide.html#walkthrough' : 'trials.html#not-open';
    return `<tr data-variant="${model.variant}"><th scope="row"><span class="variant-family">${families[model.family]}</span><a href="${target}">${model.variant}</a></th>${Object.entries(model.routes).map(([operator, state]) => `<td data-operator="${operator}" data-route="${state}"><span class="route-status route-${state}">${states[state][language]}</span></td>`).join('')}<td class="variant-progress"><p>${escape(model.progress[language])}</p>${model.note[language] ? `<p>${escape(model.note[language])}</p>` : ''}<a href="${target}">${en ? (isCandidate(model) ? 'Testing instructions & form' : 'Next step') : (isCandidate(model) ? '测试说明与反馈表' : '查看下一步')}</a></td></tr>`;
  }).join('\n');
  return `<section class="variant-coverage" aria-labelledby="variant-matrix-title" id="variant-matrix">
<div class="matrix-heading"><h3 id="variant-matrix-title">${en ? 'Compatibility by exact hardware suffix' : '完整型号兼容性与适配进度'}</h3><p>${en ? 'As of' : '更新于'} <time datetime="${data.as_of}">${data.as_of}</time> · ${data.release}</p></div>
<p class="matrix-intro">${en ? 'Find the suffix in Settings > About, then check your actual carrier. 14 listed suffixes: three automatic models, 13 manual trial combinations and six read-only combinations. New candidates have no hardware acceptance.' : '先在手机“设置 → 关于”核对完整后缀，再看实际运营商。列出 14 个后缀：3 款自动适配、13 组手动候选、6 组只读诊断；新增候选尚未真机验收。'}</p>
<ul class="matrix-legend"><li>${en ? 'Automatic: historical voice acceptance' : '自动适配：已有历史语音验收'}</li><li>${en ? 'Manual: gated local trial, autostart off' : '手动候选：条件通过后试测，不自启'}</li><li>${en ? 'Read-only: inspect and export, no install' : '只读诊断：只检查导出，不安装'}</li><li>${en ? 'Not open: stop before installation' : '暂未开放：安装前停止'}</li></ul>
<p class="table-scroll-hint" id="matrix-scroll-hint">${en ? 'On a narrow screen, swipe the table sideways; the model column stays visible. Keyboard users can focus the table and use arrow keys.' : '窄屏可左右滑动表格，型号列保持可见；键盘可聚焦表格后用方向键横向查看。'}</p>
<div class="variant-table-wrap" role="region" aria-labelledby="variant-matrix-title" aria-describedby="matrix-scroll-hint" tabindex="0"><table class="variant-table"><caption>${en ? 'Current desktop r15 routes; voice, SMS and first Root are separate acceptance scopes.' : '桌面 r15 当前流程；通话、短信和首次 Root 分别验收。'}</caption><thead><tr><th scope="col">${en ? 'Exact model' : '完整型号'}</th>${Object.values(operators).map(op => `<th scope="col">${op[language]}</th>`).join('')}<th scope="col">${en ? 'Progress / next step' : '进度 / 下一步'}</th></tr></thead><tbody>${rows}</tbody></table></div>
<p class="compatibility-note">${en ? 'All trial routes require existing valid Root/SSH, OS 10.3.3.3216, the specified USIM without ISIM, working LTE data and native-file checks. A Root recipe is not first-flash acceptance. SQW100-2 identity remains unconfirmed. Other MNCs and ISIM are outside this batch.' : '所有试测入口都要求已有有效 Root/SSH、OS 10.3.3.3216、指定无 ISIM 的 USIM、可用 LTE 数据和原生文件校验。Root 配方存在不等于首次刷写验收。SQW100-2 身份尚待核实；其他 MNC 和 ISIM 不在本批范围。'}</p>
<a class="text-link" href="trials.html">${en ? 'Get shareable instructions for each candidate' : '按型号复制或下载给测试者的说明'} →</a></section>`;
}

function trialPage(data, language) {
  const en = language === 'en';
  const prefix = en ? '../' : '';
  const candidates = data.models.filter(isCandidate);
  const cards = candidates.map(model => {
    const id = model.variant.toLowerCase();
    const route = readonly(model) ? 'read_only_lifecycle_pending' : 'manual_candidate';
    return `<section class="trial-card" id="${id}" aria-labelledby="${id}-title"><div class="trial-card-heading"><h2 id="${id}-title">${families[model.family]} · ${model.variant}</h2><span class="route-status route-${route}">${states[route][language]}</span></div>
<p>${escape(model.progress[language])} ${escape(model.note[language])}</p>
<div class="trial-actions"><button class="button button-primary" type="button" data-copy-trial="${id}-message" hidden>${en ? 'Copy instructions + form' : '复制说明和反馈表'}</button><a class="button button-secondary" href="${prefix}trials/${model.variant}.${language}.txt" download>${en ? 'Download TXT' : '下载纯文本 TXT'}</a><a class="text-link" href="#${id}">${en ? 'Link to this model' : '本型号链接'}</a></div><p class="copy-status" data-copy-status role="status" aria-live="polite"></p>
<details class="trial-details"><summary>${en ? 'Read the complete instructions and feedback form' : '展开完整步骤和反馈表'}</summary><pre class="trial-message" id="${id}-message">${escape(instructions(model, language))}</pre></details></section>`;
  }).join('\n');
  return `<section class="guide-hero" aria-labelledby="trials-title"><div class="shell"><p class="eyebrow">${data.release} · ${data.as_of}</p><h1 id="trials-title">${en ? 'Test your exact variant' : '按完整型号，开始本地试测'}</h1><p class="guide-intro">${en ? 'Eight candidate suffixes, with instructions you can forward as-is. Each includes the allowed carriers, steps, stop conditions and a feedback form. New variants are not yet hardware-accepted.' : '8 个新增候选后缀，各有一份可直接转发的说明：包含适用运营商、操作步骤、停止条件和反馈表。新增机型尚未真机验收。'}</p><div class="guide-actions"><a class="button button-primary" href="#choose-variant">${en ? 'Choose your exact suffix' : '选择完整后缀'}</a><a class="button button-secondary" href="${prefix}trials/instructions-${language}.txt" download>${en ? 'Download all eight instructions' : '下载全部 8 份说明'}</a></div></div></section>
<div class="shell trial-layout"><nav class="trial-picker" id="choose-variant" aria-label="${en ? 'Candidate hardware variants' : '候选硬件型号'}">${candidates.map(m => `<a href="#${m.variant.toLowerCase()}">${m.variant}</a>`).join('')}</nav>
<p class="compatibility-note">${en ? 'These are desktop r15 instructions. Manual candidates install and start separately; Passport SQW100-1/-3 only inspect and export. A missing Root connection does not require a wipe or flash for feedback. Do not run desktop and mobile write operations together.' : '本说明对应桌面 r15。手动候选分开安装和启动；Passport SQW100-1/-3 仅检查导出。没有 Root 连接时无需为反馈清空刷机；桌面与手机版不能同时写入。'}</p>
${cards}
<section class="trial-card" id="not-open" aria-labelledby="not-open-title"><h2 id="not-open-title">${en ? 'Other suffixes and carriers' : '其他后缀和运营商'}</h2><p>${en ? 'SQN100-3, SQC100-2 and SQW100-4 use the established automatic route. SQN100-2/-4 domestic combinations, Mobile/Unicom on SQN100-1/-5, Mobile on SQC100-4, and the unconfirmed SQW100-2 are not open for this trial. Other MNCs and ISIM are outside this batch.' : 'SQN100-3、SQC100-2、SQW100-4 继续使用已有自动适配。SQN100-2/-4 的国内组合、SQN100-1/-5 的移动和联通、SQC100-4 的移动，以及身份未确认的 SQW100-2，不开放本批试装。其他 MNC 和 ISIM 也不在本批范围。'}</p><p>${en ? 'If you want to help clarify a blocked model, send only the exact suffix, OS, carrier, city, existing LTE/Root status and a redacted Settings > About screenshot with identifiers hidden. Do not flash, install or borrow another profile to obtain that information.' : '如愿意协助核实暂未开放的型号，仅反馈完整后缀、系统、运营商、城市、已有 LTE/Root 状态，以及遮挡设备标识后的“关于”截图即可。不要为了采集信息刷机、试装或套用其他配置。'}</p><a class="text-link" href="index.html#variant-matrix">${en ? 'Back to the full compatibility table' : '返回完整兼容性进度表'} →</a></section></div>`;
}

export async function renderCompatibility(source, output) {
  const data = JSON.parse(await readFile(path.join(source, 'compatibility.json'), 'utf8'));
  await mkdir(path.join(output, 'trials'), { recursive: true });
  for (const [language, prefix] of [['zh', ''], ['en', 'en/']]) {
    for (const [file, marker, content] of [['index.html', 'compatibility', matrix(data, language)], ['trials.html', 'trials', trialPage(data, language)]]) {
      const target = path.join(output, prefix, file);
      const html = await readFile(target, 'utf8');
      const expression = new RegExp(`<!-- ${marker}:start -->[\\s\\S]*?<!-- ${marker}:end -->`);
      if (!expression.test(html)) throw new Error(`Missing ${marker} marker in ${file}`);
      await writeFile(target, html.replace(expression, `<!-- ${marker}:start -->\n${content}\n<!-- ${marker}:end -->`));
    }
    const texts = [];
    for (const model of data.models.filter(isCandidate)) {
      const text = instructions(model, language);
      await writeFile(path.join(output, 'trials', `${model.variant}.${language}.txt`), text);
      texts.push(text);
    }
    await writeFile(path.join(output, 'trials', `instructions-${language}.txt`), texts.join('\n\n============================================================\n\n'));
  }
}
