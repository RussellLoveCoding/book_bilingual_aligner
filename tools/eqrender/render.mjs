/**
 * LaTeX → SVG（MathJax 3）→ PNG（sharp），一次做完。
 *
 * 用法：
 *   node render.mjs jobs.json out_dir [scale] [--svg]
 *     jobs.json = [{"id":"eq_0001","tex":"...","display":true}, ...]
 *   --svg 额外把每个公式的 SVG 源码写到 out_dir/<id>.svg（排查用）
 *   产出 out_dir/eq_0001.png + out_dir/manifest.json
 *
 * manifest 每条：{id, file, ok, display, tag, w_px, h_px,
 *                 width_em, height_em, depth_em, err}
 *   width/height/depth_em 用于排版（em=16, ex=8 ⇒ 1ex = 0.5em）。
 *
 * 三个已解决的坑（来自《重建说明》实测）：
 *   1. 必须剥掉 <mjx-container> 外壳，只留 <svg>，否则栅格器报尺寸未定义；
 *   2. \tag{} 要剥出来单独返回（MathJax 会输出 width="100%" 撑满容器）；
 *      且必须全局剥离，minerU 有时写两个 \tag；取内容要按首尾花括号切片
 *      （\tag{A_{p}} 这种嵌套花括号不能用 \{([^}]*)\}）；
 *   3. MathJax 不抛异常，只吐 merror 红框 → 检测 data-mjx-error 判失败，
 *      否则成功率会虚报为 100%。
 */
import fs from 'node:fs';
import path from 'node:path';
import { mathjax } from 'mathjax-full/js/mathjax.js';
import { TeX } from 'mathjax-full/js/input/tex.js';
import { SVG } from 'mathjax-full/js/output/svg.js';
import { liteAdaptor } from 'mathjax-full/js/adaptors/liteAdaptor.js';
import { RegisterHTMLHandler } from 'mathjax-full/js/handlers/html.js';
import { AllPackages } from 'mathjax-full/js/input/tex/AllPackages.js';
import { createRequire } from 'node:module';

// sharp 必须走 CJS 入口：它的 ESM 入口用了 import attributes
// （`import ... with { type: 'json' }`），node 18.19 解析不了。
// 走 createRequire 拿 lib/index.js，功能完全一样。
const require = createRequire(import.meta.url);
const sharp = require('sharp');

const [, , jobsFile, outDir, scaleArg] = process.argv;
const SCALE = Number(scaleArg || 4);
const DUMP_SVG = process.argv.includes('--svg');

const adaptor = liteAdaptor();
RegisterHTMLHandler(adaptor);
// 去掉 noundefined：否则未知宏会被染成红色当成正常公式渲染，merror 检测
// 完全失效（实测 \fcac{1}{2} 假报成功）。noerrors 会吞掉错误，同理去掉。
const tex = new TeX({
  packages: AllPackages.filter((p) => p !== 'noundefined' && p !== 'noerrors'),
});
// fontCache:'none' → 每个 SVG 自包含（无 <use> 外部引用），sharp/librsvg
// 才能正确栅格化；代价是体积约 3 倍，可接受。
const svg = new SVG({ fontCache: 'none' });
const doc = mathjax.document('', { InputJax: tex, OutputJax: svg });

// ⚠ MathJax 的 SVG 靠它自己生成的 CSS 描边，独立 SVG 里必须内联这份 CSS：
// \hline（在 MathJax 里是 mtable 的 border）输出成 <line class="mjx-solid">，
// 元素上没有 stroke-width，唯一来源是 CSS 里的
//   g[data-mml-node="mtable"] > line[data-line] { stroke-width: 70px; }
// 少了它，\begin{array} 里的 \hline 会整根消失（实测 prob 1.1/1.2 的横线丢失）。
// styleSheet() 返回的是 <style> 元素本身（不是字符串），读它的文本。
const MJX_CSS = adaptor.textContent(svg.styleSheet(doc)) || '';

/** 剥 \tag{...}：返回 [去 tag 后的 tex, tag 内容 or null]；按花括号配平切片。 */
function splitTag(tex) {
  const idx = tex.indexOf('\\tag');
  if (idx < 0) return [tex, null];
  let i = tex.indexOf('{', idx);
  if (i < 0) return [tex, null];
  let depth = 0, end = -1;
  for (let k = i; k < tex.length; k++) {
    if (tex[k] === '{') depth++;
    else if (tex[k] === '}') {
      depth--;
      if (depth === 0) { end = k; break; }
    }
  }
  if (end < 0) return [tex, null];
  const tag = tex.slice(i + 1, end).trim();
  // 去掉 \tag 或 \tag* 整段（含可能的 *）
  const before = tex.slice(0, idx);
  const after = tex.slice(end + 1);
  const rest = before + after;
  // 递归：minerU 有时写两个 \tag
  const [t2, tag2] = rest.includes('\\tag') ? splitTag(rest) : [rest, null];
  return [t2, tag || tag2 || null];
}

const EX2PX = 8;                         // MathJax 默认 em=16px → 1ex = 8px
const EX2EM = 0.5;                       // 1ex = 0.5em

function metricsOf(svgStr) {
  const w = /width="([\d.]+)\s*ex"/.exec(svgStr);
  const h = /height="([\d.]+)\s*ex"/.exec(svgStr);
  const va = /vertical-align:\s*(-?[\d.]+)\s*ex/.exec(svgStr);
  return {
    width_em: w ? parseFloat(w[1]) * EX2EM : 0,
    height_em: h ? parseFloat(h[1]) * EX2EM : 0,
    depth_em: va ? -parseFloat(va[1]) * EX2EM : 0,
  };
}

const jobs = JSON.parse(fs.readFileSync(jobsFile, 'utf-8'));
fs.mkdirSync(outDir, { recursive: true });
const manifest = [];

for (const job of jobs) {
  const id = job.id;
  const [body, tag] = splitTag(job.tex || '');
  const rec = { id, file: `${id}.png`, ok: false, display: !!job.display,
                tag: tag || null, w_px: 0, h_px: 0,
                width_em: 0, height_em: 0, depth_em: 0, err: '' };
  try {
    const node = doc.convert(body, { display: !!job.display });
    let html = adaptor.outerHTML(node);
    // 错误只记账、不中止：出错的公式照样出 PNG（读者至少能看见内容），
    // ok=false + err 供上游统计/回退。以前直接 continue 会静默丢内容。
    if (!html) rec.err = 'empty';
    else if (html.indexOf('data-mjx-error') >= 0 ||
             html.indexOf('merror') >= 0) rec.err = 'merror';
    else if (html.indexOf('fill="red"') >= 0) rec.err = 'red';
    if (!html) { manifest.push(rec); continue; }
    // 剥 <mjx-container> 外壳，只留 <svg>…</svg>
    const s = html.indexOf('<svg');
    const e = html.lastIndexOf('</svg>');
    if (s < 0 || e < 0) { rec.err = 'no-svg'; manifest.push(rec); continue; }
    let svgStr = html.slice(s, e + 6);
    if (DUMP_SVG) fs.writeFileSync(path.join(outDir, `${id}.svg`), svgStr);
    // ⚠ 度量必须在 ex→px 替换之前算：替换完正则就再也匹配不到 ex 了
    // （曾经把 width_em/height_em 全算成 0，排版信息整份丢失）。
    Object.assign(rec, metricsOf(svgStr));
    // ex → px：MathJax 的 width/height 是 ex 单位，librsvg/sharp 解析不了。
    svgStr = svgStr.replace(/(-?[\d.]+(?:e-?\d+)?)ex\b/g,
                            (m, v) => `${(parseFloat(v) * EX2PX).toFixed(4)}px`);
    // 补 xmlns（librsvg 需要）
    if (svgStr.indexOf('xmlns=') < 0) {
      svgStr = svgStr.replace('<svg', '<svg xmlns="http://www.w3.org/2000/svg"');
    }
    // 内联 MathJax 的 CSS（放在最后，避免被 ex→px 正则改写）
    if (MJX_CSS) svgStr = svgStr.replace('</svg>', `<style>${MJX_CSS}</style></svg>`);
    const pngPath = path.join(outDir, `${id}.png`);
    await sharp(Buffer.from(svgStr), { density: 72 * SCALE })
      .png({ palette: true, colors: 32 })
      .toFile(pngPath);
    const meta = await sharp(pngPath).metadata();
    rec.w_px = meta.width || 0;
    rec.h_px = meta.height || 0;
    rec.ok = !rec.err;
  } catch (err) {
    rec.err = String(err && err.message || err).slice(0, 120);
  }
  manifest.push(rec);
}

// ⚠ 必须与已有 manifest **合并**，不能覆盖：调用方每次只把「增量」的几条
// 丢进来（命中缓存的不会再渲），直接覆盖会把上一次的度量整片抹掉 ——
// 实测全书第二次跑时，上一次渲过的前 40 条全被打成 err='missing'，
// 而那些 PNG 明明就在磁盘上。
const mfPath = path.join(outDir, 'manifest.json');
const merged = new Map();
try {
  for (const r of JSON.parse(fs.readFileSync(mfPath, 'utf-8'))) {
    merged.set(r.id, r);
  }
} catch (e) { /* 首次跑还没有 manifest */ }
for (const r of manifest) merged.set(r.id, r);
fs.writeFileSync(mfPath, JSON.stringify([...merged.values()], null, 1));
const ok = manifest.filter((r) => r.ok).length;
console.log(`[render] ${ok}/${manifest.length} 成功 → ${outDir}`);
const bad = manifest.filter((r) => !r.ok).slice(0, 5);
for (const b of bad) console.log(`  FAIL ${b.id}: ${b.err}`);
