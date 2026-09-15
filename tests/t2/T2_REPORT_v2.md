# T2 章内小节对齐测试报告

> 候选由 `bil/sectmine.py`（程序规则）挖出；本报告只记录 LLM 的配对结果与程序校验。**每本抽 1 章**（不是整书跑）。


## ml 第4章

```
【ml】第4章
  EN 章：Chapter 4. Training Models（文件 1 个）
  ZH 章：第4章 训练模型（文件 1 个）
  程序挖出候选：EN 20 条 / ZH 12 条（已剔章标题）
```

报文：`ml_ch4_payload.txt`


LLM units 22 条。

```
  精度（LLM 配出的都对）**22/22**
  召回（程序清单被覆盖）EN **20/20** · ZH **11/11**
  ✅ Linear Regression　|　4.1线性回归　(0.95)
  ✅ The Normal Equation　|　　(0.9)
  ✅ Computational Complexity　|　　(0.9)
  ✅ Gradient Descent　|　4.2梯度下降　(0.95)
  ✅ Batch Gradient Descent　|　　(0.9)
  ✅ Stochastic Gradient Descent　|　　(0.9)
  ✅ Mini-Batch Gradient Descent　|　　(0.9)
  ✅ Polynomial Regression　|　4.3多项式回归　(0.95)
  ✅ Learning Curves　|　4.4学习曲线　(0.95)
  ✅ 　|　偏差/方差权衡　(0.8)
  ✅ 　|　方差　(0.8)
  ✅ Regularized Linear Models　|　4.5正则化线性模型　(0.95)
  ✅ Ridge Regression　|　　(0.9)
  ✅ Lasso Regression　|　　(0.9)
  ✅ Elastic Net Regression　|　　(0.9)
  ✅ Early Stopping　|　　(0.9)
  ✅ Logistic Regression　|　4.6逻辑回归　(0.95)
  ✅ Estimating Probabilities　|　　(0.9)
  ✅ Training and Cost Function　|　　(0.9)
  ✅ Decision Boundaries　|　　(0.9)
  ✅ Softmax Regression　|　　(0.9)
  ✅ Exercises　|　4.7练习题　(0.95)
```

§4.2.3 我方校验：✅ 通过


## nexus 第1章

```
【nexus】第1章
  EN 章：Chapter 1 What Is Information?（文件 1 个）
  ZH 章：第一章信息是什么？（文件 1 个）
  程序挖出候选：EN 3 条 / ZH 4 条（已剔章标题）
```

报文：`nexus_ch1_payload.txt`


LLM units 3 条。

```
  精度（LLM 配出的都对）**3/3**
  召回（程序清单被覆盖）EN **3/3** · ZH **3/3**
  ✅ What Is Truth?　|　真相究竟是什么？　(0.95)
  ✅ What Information Does　|　信息有何作用？　(0.95)
  ✅ Information in Human History　|　人类历史的信息　(0.95)
```

§4.2.3 我方校验：✅ 通过


## prob 第8章

```
【prob】第8章
  EN 章：Sufficiency, ancillarity, and all that（文件 1 个）
  ZH 章：第 8 章 充分性与辅助性（文件 1 个）
  程序挖出候选：EN 20 条 / ZH 58 条（已剔章标题）
```

报文：`prob_ch8_payload.txt`


LLM units 20 条。

```
  精度（LLM 配出的都对）**20/20**
  召回（程序清单被覆盖）EN **20/20** · ZH **20/20**
  ✅ Sufficiency　|　充分性　(0.95)
  ✅ Fisher sufficiency　|　费希尔充分性　(0.95)
  ✅ Examples　|　示例　(0.95)
  ✅ The Blackwell–Rao theorem　|　布莱克韦尔-拉奥定理　(0.95)
  ✅ Generalized sufficiency　|　广义充分性　(0.95)
  ✅ Sufficiency plus nuisance parameters　|　带冗余参数的充分性　(0.95)
  ✅ The likelihood principle　|　似然原理　(0.95)
  ✅ Conditionality principle　|　条件原理　(0.9)
  ✅ Ancillarity　|　辅助性　(0.95)
  ✅ Generalized ancillary information　|　广义辅助信息　(0.95)
  ✅ Asymptotic likelihood: Fisher information　|　渐近似然：费希尔信息　(0.95)
  ✅ Combining evidence from different sources　|　结合不同来源的证据　(0.95)
  ✅ Pooling the data　|　合并数据　(0.95)
  ✅ Fine-grained propositions　|　细粒度命题　(0.9)
  ✅ Sam’s broken thermometer　|　萨姆的坏温度计　(0.95)
  ✅ Comments　|　评注　(0.95)
  ✅ The fallacy of sample re-use　|　样本重复使用的错误　(0.95)
  ✅ A folk theorem　|　民间定理　(0.95)
  ✅ Effect of prior information　|　先验信息的作用　(0.95)
  ✅ Clever tricks and gamesmanship　|　技巧和花招　(0.95)
```

§4.2.3 我方校验：✅ 通过


## think2 第5章

```
【think2】第5章
  EN 章：Cognitive Ease（文件 1 个）
  ZH 章：第5章 认知轻松（文件 1 个）
  程序挖出候选：EN 7 条 / ZH 6 条（已剔章标题）
```

报文：`think2_ch5_payload.txt`


LLM units 6 条。

```
  精度（LLM 配出的都对）**6/6**
  召回（程序清单被覆盖）EN **7/7** · ZH **6/6**
  ✅ ILLUSIONS OF REMEMBERING　|　记忆错觉　(0.98)
  ✅ ILLUSIONS OF TRUTH　|　真相错觉　(0.98)
  ✅ HOW TO WRITE A PERSUASIVE MESSAGE　|　怎样写出令人信服的信息　(0.95)
  ✅ STRAIN AND EFFORT　|　压力与努力　(0.95)
  ✅ THE PLEASURE OF COGNITIVE EASE　|　认知轻松的乐趣　(0.98)
  ✅ SPEAKING OF COGNITIVE EASE　|　谈谈认知轻松　(0.95)
```

§4.2.3 我方校验：✅ 通过
