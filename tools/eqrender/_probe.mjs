// 探针：打印 AllPackages 内容、SVG 输出器的 CSS、未知宏的产物。
import { mathjax } from 'mathjax-full/js/mathjax.js';
import { TeX } from 'mathjax-full/js/input/tex.js';
import { SVG } from 'mathjax-full/js/output/svg.js';
import { liteAdaptor } from 'mathjax-full/js/adaptors/liteAdaptor.js';
import { RegisterHTMLHandler } from 'mathjax-full/js/handlers/html.js';
import { AllPackages } from 'mathjax-full/js/input/tex/AllPackages.js';

const adaptor = liteAdaptor();
RegisterHTMLHandler(adaptor);
const tex = new TeX({ packages: AllPackages });
const svg = new SVG({ fontCache: 'none' });
const doc = mathjax.document('', { InputJax: tex, OutputJax: svg });

console.log('--- AllPackages ---');
console.log(AllPackages.join(', '));
console.log('含 noundefined:', AllPackages.includes('noundefined'));

console.log('--- svg.styleSheet ---');
console.log('类型:', typeof svg.styleSheet);
try {
  const css = svg.styleSheet(doc);
  console.log('长度:', css.length);
  console.log(css.slice(0, 700));
  const m = /\.mjx-solid[^}]*}/.exec(css);
  console.log('mjx-solid 规则:', m ? m[0] : '(未找到)');
} catch (e) {
  console.log('调用失败:', e.message);
}

console.log('--- 未知宏 \\fcac{1}{2} 的产物 ---');
const html = adaptor.outerHTML(doc.convert('\\fcac {1}{2}', { display: true }));
console.log(html.slice(0, 400));
console.log('含 merror:', html.includes('merror'),
            '| 含 noundefined:', html.includes('undefined'),
            '| 含 red:', html.includes('red'));
