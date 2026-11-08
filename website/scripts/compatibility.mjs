import { readFile, writeFile, mkdir } from 'node:fs/promises';
import path from 'node:path';
export const operators = { mobile: {zh:'移动',en:'Mobile'}, unicom: {zh:'联通',en:'Unicom'}, telecom: {zh:'电信',en:'Telecom'} };
const evidence = { passed:{zh:'实测可用',en:'Tested usable'}, issues:{zh:'实测有问题',en:'Tested with issues'}, failed:{zh:'实测未通过',en:'Tested unsuccessful'}, untested:{zh:'理论可试／未实测',en:'Theoretical / untested'} };
const families = {q10:'Q10',classic:'Q20 / Classic',passport:'Passport',p9983:'P’9983'};
const escape = value => String(value).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
export function instructions(model, language) {
 const en=language==='en';
 return (en ? [
 `BB10 VoLTE r42 — ${model.variant} testing instructions`,
 'All three carriers are open. Admission is independent of historical test results.',model.progress.en,
 'Requirements: Root, BB10 10.3.3.3216, matching native files, USIM without ISIM. Backup and recovery conditions are checked.',
 '1. Install the current phone app. Check the phone, then follow the backup/install or update action.',
 '2. Restart normally only when requested. A saved network policy may require another restart. Wait for VoLTE connected.',
 '3. Turn Wi-Fi off. Test incoming/outgoing calls, two-way audio, LTE and data during calls, HTTP and HTTPS.',
 '4. Send one short SMS once. Verify sent status and receipt count. Then test long SMS both ways and two identical incoming messages. Stop if pending or duplicated; do not resend delivered messages.',
 '5. Shut down normally before swapping SIMs. Keep backups. Disable and restore remains available. Never run mobile and desktop writes simultaneously.',
 'FEEDBACK FORM (blank means not tested)',`Exact model: ${model.variant}`,'App/service version:','Carrier / actual home PLMN:',
 'Incoming/outgoing calls / audio / LTE / data:','Short SMS status/count / long SMS / two identical incoming messages:','Normal restart / restoration / issues:',
 'Attach only redacted JSON or ZIP diagnostics. Never include IMSI, IMEI, ICCID, phone numbers, keys or SMS contents.',
 'Computer pairing and SSH are optional for desktop management, not everyday phone-only use.'
 ] : [
 `BB10 VoLTE r42｜${model.variant} 测试说明`,
 '移动、联通、电信均开放使用；开放入口与历史测试结论分别记录。',model.progress.zh,
 '需要 Root、BB10 10.3.3.3216、匹配原生文件及无 ISIM 的 USIM；应用会核对备份和恢复条件。',
 '1. 安装新版手机应用，检查手机，按页面提示备份并安装或更新。',
 '2. 仅在应用提示时正常重启；保存网络策略后可能需再重启一次。等待显示 VoLTE 已连接。',
 '3. 关闭 Wi-Fi，测试呼入、呼出、双向声音、通话保持 LTE、通话上网及 HTTP/HTTPS 网页。',
 '4. 先发一条短短信，只点一次发送，核对状态与条数；再测双向长短信和两条同内容收信。卡住或重复时停止，不重发已送达短信。',
 '5. 正常关机换卡，保留备份。可使用“停用并恢复”；桌面与手机不要同时执行写入任务。',
 '反馈表（留空表示未测试）',`完整型号：${model.variant}`,'应用/后台版本：','运营商/实际归属 PLMN：',
 '呼入/呼出/声音/LTE/上网：','短信状态与条数/长短信/同内容收信：','正常重启/恢复/异常：',
 '仅附脱敏 JSON 或 ZIP；不要包含 IMSI、IMEI、ICCID、号码、密钥或短信正文。',
 '电脑配对与 SSH 仅在需要桌面管理时使用，日常脱离电脑使用不需要。'
 ]).join('\n\n')+'\n';
}
function matrix(data,language) {
 const en=language==='en';
 const rows=data.models.map(m=>`<tr data-variant="${m.variant}"><th scope="row"><span class="variant-family">${families[m.family]}</span><a href="trials.html#${m.variant.toLowerCase()}">${m.variant}</a></th>${Object.keys(operators).map(op=>`<td data-operator="${op}" data-route="${m.routes[op]}"><span class="route-status evidence-${m.evidence_status[op]}">${evidence[m.evidence_status[op]][language]}</span><small>${en?'Open':'已开放'}</small></td>`).join('')}<td class="variant-progress"><p>${escape(m.progress[language])}</p><a href="trials.html#${m.variant.toLowerCase()}">${en?'Instructions & feedback':'测试说明与反馈'}</a></td></tr>`).join('\n');
 return `<section class="variant-coverage" aria-labelledby="variant-matrix-title" id="variant-matrix"><div class="matrix-heading"><h3 id="variant-matrix-title">${en?'Exact-model test records':'完整型号实测记录'}</h3><p>${data.as_of} · ${data.release}</p></div><p class="matrix-intro">${en?'All 16 catalog entries and 48 carrier combinations are open, including untested and previously unsuccessful trials. Historical evidence is not fresh acceptance of this release.':'16 个目录条目、48 个三网组合均开放，包括未实测和此前未通过的组合。历史实测不等于本次新版本全项验收。'}</p><ul class="matrix-legend">${Object.values(evidence).map(s=>`<li>${s[language]}</li>`).join('')}</ul><p class="table-scroll-hint" id="matrix-scroll-hint">${en?'Scroll horizontally to see all columns.':'左右滑动查看完整表格。'}</p><div class="variant-table-wrap" role="region" aria-labelledby="variant-matrix-title" aria-describedby="matrix-scroll-hint" tabindex="0"><table class="variant-table"><caption>${en?'Evidence is version-specific; bands, SIM and local networks affect results.':'实测按原版本与项目记录；频段、SIM 和当地网络仍影响结果。'}</caption><thead><tr><th scope="col">${en?'Exact model':'完整型号'}</th>${Object.values(operators).map(s=>`<th scope="col">${s[language]}</th>`).join('')}<th scope="col">${en?'Evidence scope':'实测范围'}</th></tr></thead><tbody>${rows}</tbody></table></div></section>`;
}
function trialPage(data,language) {
 const en=language==='en',prefix=en?'../':'';
 return `<section class="guide-hero" aria-labelledby="trials-title"><div class="shell"><p class="eyebrow">${data.release} · ${data.as_of}</p><h1 id="trials-title">${en?'Test your exact model':'按完整型号自主测试'}</h1><p class="guide-intro">${en?'All catalog models are open. Record real results without repeating completed checks.':'全部目录型号已开放。按真实结果登记，已完成项目不重复测试。'}</p><a class="button button-primary" href="${prefix}trials/instructions-${language}.txt" download>${en?'Download all instructions':'下载全部说明'}</a></div></section><div class="shell trial-layout"><nav class="trial-picker" id="choose-variant">${data.models.map(m=>`<a href="#${m.variant.toLowerCase()}">${m.variant}</a>`).join('')}</nav>${data.models.map(m=>{const id=m.variant.toLowerCase();return `<section class="trial-card" id="${id}" aria-labelledby="${id}-title"><h2 id="${id}-title">${families[m.family]} · ${m.variant}</h2><p>${escape(m.note[language])}</p><div class="trial-actions"><button class="button button-primary" type="button" data-copy-trial="${id}-message" hidden>${en?'Copy instructions + form':'复制说明和反馈表'}</button><a class="button button-secondary" href="${prefix}trials/${m.variant}.${language}.txt" download>${en?'Download TXT':'下载 TXT'}</a></div><p class="copy-status" data-copy-status role="status" aria-live="polite"></p><details class="trial-details"><summary>${en?'Instructions and feedback form':'操作说明与反馈表'}</summary><pre class="trial-message" id="${id}-message">${escape(instructions(m,language))}</pre></details></section>`;}).join('\n')}<section id="not-open"><h2>${en?'Requirements':'使用条件'}</h2><p>${en?'Test status and band estimates do not block activation. Root, OS, native files, SIM identity and recoverable backups remain checked.':'实测状态与频段估计不阻挡启用；Root、系统、原生文件、SIM 身份与可恢复备份仍需检查。'}</p><a href="index.html#variant-matrix">${en?'Full matrix':'完整适配表'}</a></section></div>`;
}
export async function renderCompatibility(source,output) {
 const data=JSON.parse(await readFile(path.join(source,'compatibility.json'),'utf8'));
 await mkdir(path.join(output,'trials'),{recursive:true});
 for(const [language,prefix] of [['zh',''],['en','en/']]) {
  for(const [file,marker,content] of [['index.html','compatibility',matrix(data,language)],['trials.html','trials',trialPage(data,language)]]) {
   const target=path.join(output,prefix,file),html=await readFile(target,'utf8');
   const expression=new RegExp(`<!-- ${marker}:start -->[\\s\\S]*?<!-- ${marker}:end -->`);
   if(!expression.test(html)) throw new Error(`Missing ${marker} marker in ${file}`);
   await writeFile(target,html.replace(expression,`<!-- ${marker}:start -->\n${content}\n<!-- ${marker}:end -->`));
  }
  const texts=[];
  for(const model of data.models){const text=instructions(model,language);await writeFile(path.join(output,'trials',`${model.variant}.${language}.txt`),text);texts.push(text);}
  await writeFile(path.join(output,'trials',`instructions-${language}.txt`),texts.join('\n\n============================================================\n\n'));
 }
}
