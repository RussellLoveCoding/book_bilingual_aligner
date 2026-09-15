# 金标准目录（我逐条推理核对的结果）

> 请直接核对下面的「英文 / 中文」配对是否成立。
> 数据来源：两侧 epub 的出版方目录（nav/ncx）；prob 中文侧来自 md 标题。
> ⚠ 标注「待核」的是我自己不确定的，请重点看。

---

## 一、概率论沉思录（Probability Theory: The Logic of Science）

### 章级（22 章 + 部 + 前后附）

```
      英文                                          中文
部 I  Part I: Principles and elementary applications    第一部分 原则和初级应用
  1   Plausible reasoning                                第 1 章 合情推理
  2   The quantitative rules                             第2章 定量规则
  3   Elementary sampling theory                         第 3 章 初等抽样论
  4   Elementary hypothesis testing                      第 4 章 初等假设检验
  5   Queer uses for probability theory                  第 5 章 概率论的怪异应用
  6   Elementary parameter estimation                    第 6 章 初等参数估计
  7   The central, Gaussian or normal distribution        第 7 章 中心分布、高斯分布或正态分布
  8   Sufficiency, ancillarity, and all that             第 8 章 充分性与辅助性
  9   Repetitive experiments: probability and frequency   第 9 章 重复实验：概率与频率
 10   Physics of 'random experiments'                    第 10 章 随机试验物理学
部II  Part II: Advanced applications                     第二部分 高级应用
 11   Discrete prior probabilities: the entropy principle 第 11 章 离散先验概率：熵原理
 12   Ignorance priors and transformation groups         第 12 章 无知先验和变换群
 13   Decision theory, historical background             第 13 章 决策论：历史背景
 14   Simple applications of decision theory             第 14 章 决策论的简单应用
 15   Paradoxes of probability theory                    第 15 章 概率论中的悖论
 16   Orthodox methods: historical background            第 16 章 正统方法：历史背景
 17   Principles and pathology of orthodox statistics    第 17 章 正统统计学原理与病理
 18   The Ap distribution and rule of succession         第18章 $A_{p}$ 分布与连续法则
 19   Physical measurements                              第 19 章 物理测量
 20   Model comparison                                   第 20 章 模型比较
 21   Outliers and robustness                            第 21 章 离群值与稳健性
 22   Introduction to communication theory               第 22 章 通信理论导论
前   Editor's foreword / Preface                         编者序 / 前言
后   Appendix A: Other approaches…                       附录A 概率论的其他流派
后   Appendix B: Mathematical formalities and style       附录 B 数学形式与风格
后   Appendix C: Convolutions and cumulants               附录 C 卷积和累积量
```

### 小节级（22 章共 307 个 EN 小节）

**主规则：两侧编号一致 → 按编号配对，284 条直接命中。**

**例外 6 条｜中文侧编号丢失，靠位置可唯一推定**

```
EN                                        ZH（md 里无编号）
3.11.1 A look ahead                       展望              （紧跟 3.11 评注）
6.9.1  Digression on optional stopping    关于可选停止       （紧跟 6.9）
9.11.1 Implied alternatives               隐含备择假设       （紧跟 9.11）
14.6.1 The classical matched filter       经典匹配滤波器     （紧跟 14.6）
17.8.1 The Bayesian safety device         贝叶斯安全装置     （紧跟 17.8）
19.2.1 Sermon on Gaussian error dists.    关于高斯误差分布的说明（紧跟 19.2）
```

**例外 1 处｜倒装（第 2 章）**

```
英文顺序：2.6.3 Venn diagrams → 2.6.4 The 'Kolmogorov axioms'
中文顺序：2.6.4 柯尔莫哥洛夫公理 → 2.6.3 维恩图      ← 与英文相反
```

**例外 17 条｜⚠ 【2026-09-15 重大更正】中文侧全都有，是我解析漏了**

这 17 条原来是「英文有、中文无此小节」——**错的**。用户指出「中文其实有 3.8.1
离题xxx」后逐条核实：它们在 md 里**没有编号、而且是裸段落（不是 `#` 标题）**，
我的提取只认 `#` 标题 → 全漏 → 误判成中文版没译。逐条定位（prob_zh.md 行号）：

```
3.8.1   离题：关于现实与模型的说明        2410
4.4.1   离题：另一种推导                  3193
4.6.1   历史题外话                       3473
5.6.1   讨论                             4157   ← 2 字标题
5.9.1   关于"怪异"                       4257
6.11.1  根据后验分布函数进行估计           4982
7.27.1  再论术语                         6614
8.10.1  细粒度命题                       7214
9.6.1   通过观察求解                      7714
10.3.1  实验证据                         8571
15.8.1  应对更大的灾难                    12384
16.8.1  沟通障碍                         13020
17.5.1  数据预滤波的愚蠢                  13344
18.11.1 无差别是基于知识还是无知？          14885
19.7.1  悖论                            15613   ← 2 字标题
20.4.1  离题：又一次说明                   15801
20.5.1  终极原因                         15987
```

**更正后的结论**：prob 两版在结构上**完全一致、零删节** ——
EN 307 个编号小节 = 中文 284 编号 + 6 个 `###` 无编号 + 17 个裸段落无编号。

⇒ **「按编号配对」的正确率上限是 100%**，只要解析层能认出
「无编号标题」和「裸段落标题」这两种形态。（已修：`titlesrc` 新增 `S4b` 源。）
⚠ 这**极可能就是 prob 段段对齐一直坏掉的解析层根因**：小节标题没识别 →
小节边界错 → 后续段落对齐全歪。

**例外 19 条｜附录子节，中文侧只有附录标题**

```
A.1–A.5（5）   B.1–B.9（含 B.5.1–B.5.3，共 12）   C.1–C.2（2）
```

**⚠ 待核 2 条｜中文有、英文目录里没有**

```
第 8 章：8.5 似然原理 与 8.6 辅助性 之间  →  「条件原理」
第17章：17.3 无偏估计的病理 与 17.4 之间 →  「补救措施」
我的猜测：是英文版 8.5 / 17.3 段内的小标题，未列入英文目录。不敢确定。
```

**中文版自带、英文版没有的 11 篇后附文章**：一位物理学家的概率观 / 概率论公理与可列可加性 / 也论无穷大 / 随机变量的迷雾 / 波利亚的合情推理 / 杰弗里斯概率论 / 丹尼斯·林德利的概率统计思想 / 频率派、客观贝叶斯派、主观贝叶斯派，究竟谁正确？ / 概率论与因果推断 / 本书的影响 / 概率观世界 / 翻译因缘。

---

## 二、思考，快与慢（第二版）

### 5 部

```
Part 1: TWO SYSTEMS             第一部分 两个系统
Part 2: HEURISTICS AND BIASES   第二部分 启发式与偏差
Part 3: OVERCONFIDENCE          第三部分 过度自信
Part 4: CHOICES                 第四部分 选择
Part 5: TWO SELVES              第五部分 两个自我
```

### 38 章（全部按编号 1:1）

```
 1  The Characters of the Story            第1章 故事中的角色
 2  Attention and Effort                   第2章 注意力与努力
 3  The Lazy Controller                    第3章 懒惰的掌控者
 4  The Associative Machine                第4章 关联机器
 5  Cognitive Ease                         第5章 认知轻松
 6  Norms, Surprises, and Causes           第6章 常态、意外及原因
 7  A Machine for Jumping to Conclusions   第7章 妄下结论的机器
 8  How Judgments Happen                   第8章 判断是如何发生的
 9  Answering an Easier Question           第9章 回答一个更简单的问题
10  The Law of Small Numbers               第10章 小数定律
11  Anchors                                第11章 锚定
12  The Science of Availability            第12章 可得性的科学
13  Availability, Emotion, and Risk        第13章 可得性、情感和风险
14  Tom W's Specialty                      第14章 汤姆的专业
15  Linda: Less is More                    第15章 琳达问题：少即是多
16  Causes Trump Statistics                第16章 原因胜过统计
17  Regression to the Mean                 第17章 回归均值
18  Taming Intuitive Predictions           第18章 驯服直觉性预测
19  The Illusion of Understanding          第19章 理解的错觉
20  The Illusion of Validity               第20章 有效性错觉
21  Intuitions vs. Formulas                第21章 直觉与公式
22  Expert Intuition: When Can We Trust It? 第22章 专家直觉何时可信？
23  The Outside View                       第23章 外部视角
24  The Engine of Capitalism               第24章 资本主义的引擎
25  Bernoulli's Errors                     第25章 伯努利的错误
26  Prospect Theory                        第26章 前景理论
27  The Endowment Effect                   第27章 禀赋效应
28  Bad Events                             第28章 负面事件
29  The Fourfold Pattern                   第29章 四重模式
30  Rare Events                            第30章 罕见事件
31  Risk Policies                          第31章 风险政策
32  Keeping Score                          第32章 记分
33  Reversals                              第33章 逆转
34  Frames and Reality                     第34章 框架与现实
35  Two Selves                             第35章 两个自我
36  Life as a Story                        第36章 人生是个故事
37  Experienced Well-Being                 第37章 体验幸福
38  Thinking About Life                    第38章 思考人生
```

### 其他

```
Introduction                                             序言
Conclusions                                              结论
Appendix A: Judgment Under Uncertainty: Heuristics…      附录A 不确定状况下的判断
Appendix B: Choices, Values, and Frames                  附录B 选择、价值与框架
Acknowledgments                                          致谢
Copyright Page（英文在末尾）                              版权信息（中文在开头）  ← 位置不同
```

**英文有、中文没有**：Cover / Title Page / About the Author / Dedication / Notes / Follow Penguin
**中文有、英文没有**：UnKnown（1 条，疑似制作噪音）

---

## 三、机器学习实战（第 3 版）

### 2 部 + 19 章（注意：第 3 版只有两部分）

```
I.  The Fundamentals of Machine Learning          第一部分 机器学习的基础知识
 1  The Machine Learning Landscape                第1章 机器学习概览
 2  End-to-End Machine Learning Project           第2章 端到端机器学习项目
 3  Classification                                第3章 分类
 4  Training Models                               第4章 训练模型
 5  Support Vector Machines                       第5章 支持向量机
 6  Decision Trees                                第6章 决策树
 7  Ensemble Learning and Random Forests          第7章 集成学习和随机森林
 8  Dimensionality Reduction                      第8章 降维
 9  Unsupervised Learning Techniques              第9章 无监督学习技术
II. Neural Networks and Deep Learning             第二部分 神经网络与深度学习
10  Introduction to Artificial Neural Networks with Keras  第10章 Keras人工神经网络简介
11  Training Deep Neural Networks                 第11章 训练深度神经网络
12  Custom Models and Training with TensorFlow    第12章 使用TensorFlow自定义模型和训练
13  Loading and Preprocessing Data with TensorFlow 第13章 使用TensorFlow加载和预处理数据
14  Deep Computer Vision Using CNN                第14章 使用卷积神经网络进行深度计算机视觉
15  Processing Sequences Using RNNs and CNNs      第15章 使用RNN和CNN处理序列
16  Natural Language Processing with RNNs and Attention 第16章 基于RNN和注意力机制的自然语言处理
17  Autoencoders, GANs, and Diffusion Models      第17章 自动编码器、GAN和扩散模型
18  Reinforcement Learning                        第18章 强化学习
19  Training and Deploying TensorFlow Models at Scale  第19章 大规模训练和部署TensorFlow模型

Preface                                           前言
A. Machine Learning Project Checklist             附录A 机器学习项目清单
B. Autodiff                                       附录B 自动微分
C. Special Data Structures                        附录C 特殊数据结构
D. TensorFlow Graphs                              附录D TensorFlow图
```

**英文有、中文没有**：书名行 / Index
**中文有、英文没有**：O'Reilly Media，Inc. 介绍 / 作者介绍 / 封面介绍 / 版权信息

⚠ **英文目录到小节级（471 条）但只有标题、没有编号**（`What Is Machine Learning?`），
中文目录只到章级（30 条）→ 小节金标准**无法从目录建立**。

---

## 四、智人之上（Nexus）

⚠ **这份最不可靠**：工作区里的「英文侧」是我们自己 emit 的单语版，它的
nav 标题已经中文化（`封面`/`扉页`），**原始书店版不在工作区**。英文章名我拿不到，
所以下面**只有编号对应，无法核对英文标题**。

```
序言   Prologue                          序言
 1     Chapter 1                          第一章 信息是什么？
 2     Chapter 2                          第二章 故事：无限的联结
 3     Chapter 3                          第三章 文件：纸老虎也会咬人
 4     Chapter 4                          第四章 错误：绝对正确是一种幻想
 5     Chapter 5                          第五章 抉择：民主与极权制度简史
 6     Chapter 6                          第六章 新成员：与众不同的计算机
 7     Chapter 7                          第七章 永不停歇：网络永远持续运行
 8     Chapter 8                          第八章 可能出错：谬误百出的网络
 9     Chapter 9                          第九章 民主制度：我们还能对话吗？
10     Chapter 10                         第十章 极权主义：所有力量归于算法？
11     Chapter 11                         第十一章 硅幕：全球帝国还是全球分裂？
结语   Epilogue                          结语
致谢   Acknowledgments                   致谢
```

**两侧都混进同一层级的章内小标题**（英文 8 条 / 中文 4 条，数量不等）：
英文 The Biological Dramas / Print, Science, and Witches / Mass Media Makes
Mass Democracy Possible / Total Control / What Are the Implications? /
The Calculus of Suffering / The Right to an Explanation / The Global Bond
中文 生物戏剧 / 印刷、科学与女巫 / 20世纪：大众民主，也是大众极权 / 新女巫 /
得到解释的权利 / 人类的选择

---

## 需要你核对的点（按重要性）

1. **prob 的 6 条「编号丢失」推定**是否成立（`展望`=3.11.1 等）？
2. **prob 的 2 条待核**（`条件原理`、`补救措施`）到底对应英文什么？
3. **think2 的 38 章**有没有哪一对其实不对（虽然编号都对得上）？
4. **nexus 的章名**——要给我原始 epub 我才能核英文标题。
