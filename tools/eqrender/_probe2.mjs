// 探针 3：styleSheet() 返回的是 <style> 元素（LiteElement）本身，读它的文本。
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

const el = svg.styleSheet(doc);
console.log('元素名:', el && el.kind);
const css = adaptor.textContent(el);
console.log('CSS 长度:', css.length);
console.log('---- CSS 全文 ----');
console.log(css);
