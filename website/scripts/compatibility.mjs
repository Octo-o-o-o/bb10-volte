import { readFile, writeFile, mkdir } from 'node:fs/promises';
import path from 'node:path';
export const operators = { mobile: {zh:'移动',en:'Mobile'}, unicom: {zh:'联通',en:'Unicom'}, telecom: {zh:'电信',en:'Telecom'} };
const evidence = { passed:{zh:'能用',en:'Works'}, issues:{zh:'有问题',en:'Issues'}, failed:{zh:'没通过',en:'Did not work'}, untested:{zh:'还没测',en:'Not tested'} };
const families = {q10:'Q10',classic:'Q20 / Classic',passport:'Passport',p9983:'P’9983'};
const escape = value => String(value).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;');
export function instructions(model, language) {
 const en=language==='en';
 return (en ? [
 `BB10 VoLTE r44 — ${model.variant} testing instructions`,
 'All three carriers are open. The labels are old results, not a new pass.',model.evidence_summary.en,
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
 `BB10 VoLTE r44｜${model.variant} 测试说明`,
 '移动、联通、电信都能试。格子里是以前的结果，不是这版又测过。',model.evidence_summary.zh,
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
 ]).filter(Boolean).join('\n\n')+'\n';
}
function matrix(data,language) {
 const en=language==='en';
 const rows=data.models.map(m=>{const extra=m.note[language].trim();return `<tr data-variant="${m.variant}"><th scope="row"><span class="variant-family">${families[m.family]}</span><a href="trials.html#${m.variant.toLowerCase()}">${m.variant}</a></th>${Object.keys(operators).map(op=>`<td data-operator="${op}" data-route="${m.routes[op]}"><span class="route-status evidence-${m.evidence_status[op]}">${evidence[m.evidence_status[op]][language]}</span></td>`).join('')}<td class="variant-progress">${extra?`<p>${escape(extra)}</p>`:''}<a href="trials.html#${m.variant.toLowerCase()}">${en?'Notes':'说明'}</a></td></tr>`;}).join('\n');
 return `<section class="variant-coverage" aria-labelledby="variant-matrix-title" id="variant-matrix"><div class="matrix-heading"><h3 id="variant-matrix-title">${en?'Exact-model results':'完整型号结果'}</h3><p>${data.as_of} · ${data.release}</p></div><p class="matrix-intro">${en?'All 16 models can be tried. A cell only says what was tested before.':'16 个型号都能试。格子只写以前测得怎么样。'}</p><ul class="matrix-legend">${Object.values(evidence).map(s=>`<li>${s[language]}</li>`).join('')}</ul><p class="table-scroll-hint" id="matrix-scroll-hint">${en?'Scroll sideways for every column.':'左右滑动看完整表格。'}</p><div class="variant-table-wrap" role="region" aria-labelledby="variant-matrix-title" aria-describedby="matrix-scroll-hint" tabindex="0"><table class="variant-table"><caption>${en?'Earlier result for each carrier. Local coverage still matters.':'每家运营商以前的结果。当地网络仍会影响。'}</caption><thead><tr><th scope="col">${en?'Model':'型号'}</th>${Object.values(operators).map(s=>`<th scope="col">${s[language]}</th>`).join('')}<th scope="col">${en?'Note':'备注'}</th></tr></thead><tbody>${rows}</tbody></table></div></section>`;
}
function trialPage(data,language) {
 const en=language==='en',prefix=en?'../':'';
 return `<section class="guide-hero" aria-labelledby="trials-title"><div class="shell"><p class="eyebrow">${data.release} · ${data.as_of}</p><h1 id="trials-title">${en?'Test your exact model':'按完整型号自主测试'}</h1><p class="guide-intro">${en?'Pick your model and test it. Skip checks you already finished.':'选中你的型号再测。已经做过的项目不用重测。'}</p><a class="button button-primary" href="${prefix}trials/instructions-${language}.txt" download>${en?'Download all instructions':'下载全部说明'}</a></div></section><div class="shell trial-layout"><nav class="trial-picker" id="choose-variant">${data.models.map(m=>`<a href="#${m.variant.toLowerCase()}">${m.variant}</a>`).join('')}</nav>${data.models.map(m=>{const id=m.variant.toLowerCase();const extra=m.note[language].trim();return `<section class="trial-card" id="${id}" aria-labelledby="${id}-title"><h2 id="${id}-title">${families[m.family]} · ${m.variant}</h2>${extra?`<p>${escape(extra)}</p>`:''}<div class="trial-actions"><button class="button button-primary" type="button" data-copy-trial="${id}-message" hidden>${en?'Copy instructions + form':'复制说明和反馈表'}</button><a class="button button-secondary" href="${prefix}trials/${m.variant}.${language}.txt" download>${en?'Download TXT':'下载 TXT'}</a></div><p class="copy-status" data-copy-status role="status" aria-live="polite"></p><details class="trial-details"><summary>${en?'Instructions and feedback form':'操作说明与反馈表'}</summary><pre class="trial-message" id="${id}-message">${escape(instructions(m,language))}</pre></details></section>`;}).join('\n')}<section id="not-open"><h2>${en?'Requirements':'使用条件'}</h2><p>${en?'The result label does not stop you. You still need Root, a matching system and native files, and a backup you can restore.':'结果不会拦你。仍要 Root、对得上的系统和原生文件，以及能恢复的备份。'}</p><a href="index.html#variant-matrix">${en?'Full matrix':'完整适配表'}</a></section></div>`;
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
