# T1 章级标题对齐（用 `cli.map_titles` 内核）

> 输入 = 程序切出的章单元标题表（每侧几十行）；输出 = index mapping。
> 期望配对 = **两侧同键**（章/部/附录按编号、前后置按序号）——
> 这就是 `dbg_align_eval` V3 的判据（四本实测 chapter 级 precision 100%）。


## ml

EN 26 行 / ZH 26 行

```
  配出 26 对 → TP 26 · FP 0 · FN 0　P 100.0% · R 100.0%（期望 26 对 = 两侧同键）
  —— 全部 ——
  ✅ Preface                                     | 前言
  ✅ Part I. The Fundamentals of Machine Learning| 第一部分
  ✅ Chapter 1. The Machine Learning Landscape   | 第1章 机器学习概览
  ✅ Chapter 2. End-to-End Machine Learning Proje| 第2章 端到端机器学习项目
  ✅ Chapter 3. Classification                   | 第3章 分类
  ✅ Chapter 4. Training Models                  | 第4章 训练模型
  ✅ Chapter 5. Support Vector Machines          | 第5章 支持向量机
  ✅ Chapter 6. Decision Trees                   | 第6章 决策树
  ✅ Chapter 7. Ensemble Learning and Random Fore| 第7章 集成学习和随机森林
  ✅ Chapter 8. Dimensionality Reduction         | 第8章 降维
  ✅ Chapter 9. Unsupervised Learning Techniques | 第9章 无监督学习技术
  ✅ Part II. Neural Networks and Deep Learning  | 第二部分
  ✅ Chapter 10. Introduction to Artificial Neura| 第10章 Keras人工神经网络简介
  ✅ Chapter 11. Training Deep Neural Networks   | 第11章 训练深度神经网络
  ✅ Chapter 12. Custom Models and Training with | 第12章 使用TensorFlow自定义模型和训练
  ✅ Chapter 13. Loading and Preprocessing Data w| 第13章 使用TensorFlow加载和预处理数据
  ✅ Chapter 14. Deep Computer Vision Using Convo| 第14章 使用卷积神经网络进行深度计算机视觉
  ✅ Chapter 15. Processing Sequences Using RNNs | 第15章 使用RNN和CNN处理序列
  ✅ Chapter 16. Natural Language Processing with| 第16章 基于RNN和注意力机制的自然语言处理
  ✅ Chapter 17. Autoencoders, GANs, and Diffusio| 第17章 自动编码器、GAN和扩散模型
  ✅ Chapter 18. Reinforcement Learning          | 第18章 强化学习
  ✅ Chapter 19. Training and Deploying TensorFlo| 第19章 大规模训练和部署TensorFlow模型
  ✅ Appendix A. Machine Learning Project Checkli| 附录A
  ✅ Appendix B. Autodiff                        | 附录B
  ✅ Appendix C. Special Data Structures         | 附录C
  ✅ Appendix D. TensorFlow Graphs               | 附录D
```

⏱ 0.0s


## nexus

EN 17 行 / ZH 14 行

```
  配出 14 对 → TP 14 · FP 0 · FN 0　P 100.0% · R 100.0%（期望 14 对 = 两侧同键）
  单侧为空（按 unpaired 计）3 条：
  · Part I ↔ （空）
  · Part II ↔ （空）
  · Part III ↔ （空）
  —— 全部 ——
  ✅ Prologue                                    | 序言
  ✅ Chapter 1 What Is Information?              | 第一章信息是什么？
  ✅ Chapter 2 Stories: Unlimited Connections    | 第二章故事：无限的联结
  ✅ Chapter 3 Documents: The Bite of the Paper T| 第三章文件：纸老虎也会咬人
  ✅ Chapter 4 Errors: The Fantasy of Infallibili| 第四章错误：绝对正确是一种幻想
  ✅ Chapter 5 Decisions: A Brief History of Demo| 第五章抉择：民主与极权制度简史
  ✅ Chapter 6 The New Members: How Computers Are| 第六章新成员：与众不同的计算机
  ✅ Chapter 7 Relentless: The Network Is Always | 第七章永不停歇：网络永远持续运行
  ✅ Chapter 8 Fallible: The Network Is Often Wro| 第八章可能出错：谬误百出的网络
  ✅ Chapter 9 Democracies: Can We Still Hold a C| 第九章民主制度：我们还能对话吗？
  ✅ Chapter 10 Totalitarianism: All Power to the| 第十章极权主义：所有力量归于算法？
  ✅ Chapter 11 The Silicon Curtain: Global Empir| 第十一章硅幕：全球帝国还是全球分裂？
  ✅ Epilogue                                    | 结语
  ✅ Acknowledgments                             | 致谢
```

⏱ 0.0s


## prob

EN 28 行 / ZH 31 行

```
  配出 27 对 → TP 27 · FP 0 · FN 1　P 100.0% · R 96.4%（期望 28 对 = 两侧同键）
  漏配的：
     ✗ Other approaches to probability theory ｜ 附录A 概率论的其他流派
  单侧为空（按 unpaired 计）1 条：
  · Other approaches to probability theory ↔ （空）
  —— 全部 ——
  ✅ Editor’s foreword                           | 编者序
  ✅ Principles and elementary applications      | 第一部分 原则和初级应用
  ✅ Plausible reasoning                         | 第 1 章 合情推理
  ✅ The quantitative rules                      | 第2章 定量规则
  ✅ Elementary sampling theory                  | 第 3 章 初等抽样论
  ✅ Elementary hypothesis testing               | 第 4 章 初等假设检验
  ✅ Queer uses for probability theory           | 第 5 章 概率论的怪异应用
  ✅ Elementary parameter estimation             | 第 6 章 初等参数估计
  ✅ The central, Gaussian or normal distribution| 第 7 章 中心分布、高斯分布或正态分布
  ✅ Sufficiency, ancillarity, and all that      | 第 8 章 充分性与辅助性
  ✅ Repetitive experiments: probability and freq| 第 9 章 重复实验：概率与频率
  ✅ Physics of ‘random experiments’             | 第 10 章 随机试验物理学
  ✅ Advanced applications                       | 第二部分 高级应用
  ✅ Discrete prior probabilities: the entropy pr| 第 11 章 离散先验概率：熵原理
  ✅ Ignorance priors and transformation groups  | 第 12 章 无知先验和变换群
  ✅ Decision theory, historical background      | 第 13 章 决策论：历史背景
  ✅ Simple applications of decision theory      | 第 14 章 决策论的简单应用
  ✅ Paradoxes of probability theory             | 第 15 章 概率论中的悖论
  ✅ Orthodox methods: historical background     | 第 16 章 正统方法：历史背景
  ✅ Principles and pathology of orthodox statist| 第 17 章 正统统计学原理与病理
  ✅ The Ap distribution and rule of succession  | 第18章 $A_{p}$ 分布与连续法则
  ✅ Physical measurements                       | 第 19 章 物理测量
  ✅ Model comparison                            | 第 20 章 模型比较
  ✅ Outliers and robustness                     | 第 21 章 离群值与稳健性
  ✅ Introduction to communication theory        | 第 22 章 通信理论导论
  ✅ Mathematical formalities and style          | 附录 B 数学形式与风格
  ✅ Convolutions and cumulants                  | 附录 C 卷积和累积量
```

⏱ 0.0s


## think2

EN 43 行 / ZH 48 行

```
  配出 43 对 → TP 43 · FP 0 · FN 0　P 100.0% · R 100.0%（期望 43 对 = 两侧同键）
  —— 全部 ——
  ✅ Introduction                                | 序言
  ✅ The Characters of the Story                 | 第1章 故事中的角色
  ✅ Attention and Effort                        | 第2章 脑力劳动
  ✅ The Lazy Controller                         | 第3章 懒惰的掌控者
  ✅ The Associative Machine                     | 第4章 促发的奇迹
  ✅ Cognitive Ease                              | 第5章 认知轻松
  ✅ Norms, Surprises, and Causes                | 第6章 常态、意外及原因
  ✅ A Machine for Jumping to Conclusions        | 第7章 妄下结论的机器
  ✅ How Judgments Happen                        | 第8章 判断是如何发生的
  ✅ Answering an Easier Question                | 第9章 回答一个更简单的问题
  ✅ The Law of Small Numbers                    | 第10章 小数定律
  ✅ Anchors                                     | 第11章 锚定
  ✅ The Science of Availability                 | 第12章 可得性的科学
  ✅ Availability, Emotion, and Risk             | 第13章 可得性、情感和风险
  ✅ Tom W’s Specialty                           | 第14章 汤姆的专业
  ✅ Linda: Less is More                         | 第15章 琳达问题：少即是多
  ✅ Causes Trump Statistics                     | 第16章 原因胜过统计
  ✅ Regression to the Mean                      | 第17章 回归均值
  ✅ Taming Intuitive Predictions                | 第18章 驯服直觉性预测
  ✅ The Illusion of Understanding               | 第19章 理解的错觉
  ✅ The Illusion of Validity                    | 第20章 有效性错觉
  ✅ Intuitions vs. Formulas                     | 第21章 直觉与公式
  ✅ Expert Intuition: When Can We Trust It?     | 第22章 专家直觉何时可信？
  ✅ The Outside View                            | 第23章 外部视角
  ✅ The Engine of Capitalism                    | 第24章 资本主义的引擎
  ✅ Bernoulli’s Errors                          | 第25章 伯努利的错误
  ✅ Prospect Theory                             | 第26章 前景理论
  ✅ The Endowment Effect                        | 第27章 禀赋效应
  ✅ Bad Events                                  | 第28章 负面事件
  ✅ The Fourfold Pattern                        | 第29章 四重模式
  ✅ Rare Events                                 | 第30章 罕见事件
  ✅ Risk Policies                               | 第31章 风险政策
  ✅ Keeping Score                               | 第32章 记分
  ✅ Reversals                                   | 第33章 逆转
  ✅ Frames and Reality                          | 第34章 框架与现实
  ✅ Two Selves                                  | 第35章 体验效用
  ✅ Life as a Story                             | 第36章 人生是个故事
  ✅ Experienced Well-Being                      | 第37章 体验幸福
  ✅ Thinking About Life                         | 第38章 思考人生
  ✅ Conclusions                                 | 结论
  ✅ Appendix A: [1]                             | 附录 A
  ✅ Appendix B: [1]                             | 附录 B
  ✅ Acknowledgments                             | 致谢
```

⏱ 0.0s
