> 机器学习实战（第3版）　中英文「章 + 小节」全量清单（金标准底稿，由 `tools/mk_gold_doc.py` 生成）


# 机器学习实战（第3版）

- 英文侧：`.workbuddy/tmp/books/ml_en.epub`　**26 单元**
- 中文侧：`.workbuddy/tmp/books/ml_zh.epub`　**26 单元**

## 章级对照

| # | 英文 | 中文 | EN 小节 | ZH 小节 |
|---|---|---|---:|---:|
| 前置 | Preface | 前言 | 13 | 13 |
| 第1部 | Part I. The Fundamentals of Machine Learning | 第一部分 | 0 | 1 |
| 第1章 | Chapter 1. The Machine Learning Landscape | 第1章 机器学习概览 | 28 | 19 |
| 第2章 | Chapter 2. End-to-End Machine Learning Project | 第2章 端到端机器学习项目 | 35 | 12 |
| 第3章 | Chapter 3. Classification | 第3章 分类 | 13 | 9 |
| 第4章 | Chapter 4. Training Models | 第4章 训练模型 | 20 | 11 |
| 第5章 | Chapter 5. Support Vector Machines | 第5章 支持向量机 | 12 | 9 |
| 第6章 | Chapter 6. Decision Trees | 第6章 决策树 | 11 | 11 |
| 第7章 | Chapter 7. Ensemble Learning and Random Forests | 第7章 集成学习和随机森林 | 14 | 6 |
| 第8章 | Chapter 8. Dimensionality Reduction | 第8章 降维 | 18 | 7 |
| 第9章 | Chapter 9. Unsupervised Learning Techniques | 第9章 无监督学习技术 | 17 | 11 |
| 第2部 | Part II. Neural Networks and Deep Learning | 第二部分 | 0 | 1 |
| 第10章 | Chapter 10. Introduction to Artificial Neural Networ | 第10章 Keras人工神经网络简介 | 25 | 11 |
| 第11章 | Chapter 11. Training Deep Neural Networks | 第11章 训练深度神经网络 | 30 | 11 |
| 第12章 | Chapter 12. Custom Models and Training with TensorFl | 第12章 使用TensorFlow自定义模型和训练 | 21 | 5 |
| 第13章 | Chapter 13. Loading and Preprocessing Data with Tens | 第13章 使用TensorFlow加载和预处理数据 | 26 | 6 |
| 第14章 | Chapter 14. Deep Computer Vision Using Convolutional | 第14章 使用卷积神经网络进行深度计算机视觉 | 28 | 16 |
| 第15章 | Chapter 15. Processing Sequences Using RNNs and CNNs | 第15章 使用RNN和CNN处理序列 | 21 | 9 |
| 第16章 | Chapter 16. Natural Language Processing with RNNs an | 第16章 基于RNN和注意力机制的自然语言处理 | 19 | 13 |
| 第17章 | Chapter 17. Autoencoders, GANs, and Diffusion Models | 第17章 自动编码器、GAN和扩散模型 | 21 | 11 |
| 第18章 | Chapter 18. Reinforcement Learning | 第18章 强化学习 | 19 | 13 |
| 第19章 | Chapter 19. Training and Deploying TensorFlow Models | 第19章 大规模训练和部署TensorFlow模型 | 31 | 18 |
| 附录A | Appendix A. Machine Learning Project Checklist | 附录A | 8 | 8 |
| 附录B | Appendix B. Autodiff | 附录B | 4 | 5 |
| 附录C | Appendix C. Special Data Structures | 附录C | 6 | 7 |
| 附录D | Appendix D. TensorFlow Graphs | 附录D | 6 | 7 |

## 逐章小节

### [前置] Preface　／　前言

**EN 13 条**

- `L1` The Machine Learning Tsunami
- `L1` Machine Learning in Your Projects
- `L1` Objective and Approach
- `L1` Code Examples
- `L1` Prerequisites
- `L1` Roadmap
- `L1` Changes Between the First and the Second Edition
- `L1` Changes Between the Second and the Third Edition
- `L1` Other Resources
- `L1` Conventions Used in This Book
- `L1` O’Reilly Online Learning
- `L1` How to Contact Us
- `L1` Acknowledgments

**ZH 13 条**

- `L2` 机器学习海啸
- `L2` 你项目中的机器学习
- `L2` 目标与方法
- `L2` 示例代码
- `L2` 先决条件
- `L2` 路线图
- `L2` 第1版和第2版之间的变化
- `L2` 第2版和第3版之间的变化
- `L2` 其他资源
- `L2` 排版约定
- `L2` 如何联系我们
- `L1` O'Reilly Media，Inc.
- `L2` 致谢

### [第1部] Part I. The Fundamentals of Machine Learning　／　第一部分

**EN 0 条**


**ZH 1 条**

- `L1` 机器学习的基础知识

### [第1章] Chapter 1. The Machine Learning Landscape　／　第1章 机器学习概览

**EN 28 条**

- `L1` What Is Machine Learning?
- `L1` Why Use Machine Learning?
- `L1` Examples of Applications
- `L1` Types of Machine Learning Systems
- `L2` Training Supervision
- `L3` Supervised learning
- `L3` Unsupervised learning
- `L3` Semi-supervised learning
- `L3` Self-supervised learning
- `L3` Reinforcement learning
- `L2` Batch Versus Online Learning
- `L3` Batch learning
- `L3` Online learning
- `L2` Instance-Based Versus Model-Based Learning
- `L3` Instance-based learning
- `L3` Model-based learning and a typical machine learning workflow
- `L1` Main Challenges of Machine Learning
- `L2` Insufficient Quantity of Training Data
- `L2` Nonrepresentative Training Data
- `L2` Poor-Quality Data
- `L2` Irrelevant Features
- `L2` Overfitting the Training Data
- `L2` Underfitting the Training Data
- `L2` Stepping Back
- `L1` Testing and Validating
- `L2` Hyperparameter Tuning and Model Selection
- `L2` Data Mismatch
- `L1` Exercises

**ZH 19 条**

- `L3` 1.1什么是机器学习
- `L3` 1.2为什么使用机器学习
- `L3` 1.3应用示例
- `L3` 1.4机器学习系统的类型
- `L2` 监督学习
- `L2` 无监督学习
- `L2` 半监督学习
- `L2` 自监督学习
- `L2` 强化学习
- `L2` 批量学习
- `L2` 在线学习
- `L2` 基于实例的学习
- `L2` 基于模型的学习和典型的机器学习工作流程
- `L3` 1.5机器学习的主要挑战
- `L2` 数据的不合理有效性
- `L2` 采样偏差的示例
- `L3` 1.6测试和验证
- `L2` 没有免费的午餐定理
- `L3` 1.7练习题

### [第2章] Chapter 2. End-to-End Machine Learning Project　／　第2章 端到端机器学习项目

**EN 35 条**

- `L1` Working with Real Data
- `L1` Look at the Big Picture
- `L2` Frame the Problem
- `L2` Select a Performance Measure
- `L2` Check the Assumptions
- `L1` Get the Data
- `L2` Running the Code Examples Using Google Colab
- `L2` Saving Your Code Changes and Your Data
- `L2` The Power and Danger of Interactivity
- `L2` Book Code Versus Notebook Code
- `L2` Download the Data
- `L2` Take a Quick Look at the Data Structure
- `L2` Create a Test Set
- `L1` Explore and Visualize the Data to Gain Insights
- `L2` Visualizing Geographical Data
- `L2` Look for Correlations
- `L2` Experiment with Attribute Combinations
- `L1` Prepare the Data for Machine Learning Algorithms
- `L2` Clean the Data
- `L2` Handling Text and Categorical Attributes
- `L2` Feature Scaling and Transformation
- `L2` Custom Transformers
- `L2` Transformation Pipelines
- `L1` Select and Train a Model
- `L2` Train and Evaluate on the Training Set
- `L2` Better Evaluation Using Cross-Validation
- `L1` Fine-Tune Your Model
- `L2` Grid Search
- `L2` Randomized Search
- `L2` Ensemble Methods
- `L2` Analyzing the Best Models and Their Errors
- `L2` Evaluate Your System on the Test Set
- `L1` Launch, Monitor, and Maintain Your System
- `L1` Try It Out!
- `L1` Exercises

**ZH 12 条**

- `L3` 2.1使用真实数据
- `L3` 2.2放眼大局
- `L2` 流水线
- `L3` 2.3获取数据
- `L3` 2.4探索和可视化数据以获得见解
- `L3` 2.5为机器学习算法准备数据
- `L2` Scikit-Learn的设计
- `L3` 2.6选择和训练模型
- `L3` 2.7微调模型
- `L3` 2.8启动、监控和维护系统
- `L3` 2.9试试看
- `L3` 2.10练习题

### [第3章] Chapter 3. Classification　／　第3章 分类

**EN 13 条**

- `L1` MNIST
- `L1` Training a Binary Classifier
- `L1` Performance Measures
- `L2` Measuring Accuracy Using Cross-Validation
- `L2` Confusion Matrices
- `L2` Precision and Recall
- `L2` The Precision/Recall Trade-off
- `L2` The ROC Curve
- `L1` Multiclass Classification
- `L1` Error Analysis
- `L1` Multilabel Classification
- `L1` Multioutput Classification
- `L1` Exercises

**ZH 9 条**

- `L3` 3.1 MNIST
- `L3` 3.2训练二元分类器
- `L3` 3.3性能测量
- `L2` 实现交叉验证
- `L3` 3.4多类分类
- `L3` 3.5错误分析
- `L3` 3.6多标签分类
- `L3` 3.7多输出分类
- `L3` 3.8练习题

### [第4章] Chapter 4. Training Models　／　第4章 训练模型

**EN 20 条**

- `L1` Linear Regression
- `L2` The Normal Equation
- `L2` Computational Complexity
- `L1` Gradient Descent
- `L2` Batch Gradient Descent
- `L2` Stochastic Gradient Descent
- `L2` Mini-Batch Gradient Descent
- `L1` Polynomial Regression
- `L1` Learning Curves
- `L1` Regularized Linear Models
- `L2` Ridge Regression
- `L2` Lasso Regression
- `L2` Elastic Net Regression
- `L2` Early Stopping
- `L1` Logistic Regression
- `L2` Estimating Probabilities
- `L2` Training and Cost Function
- `L2` Decision Boundaries
- `L2` Softmax Regression
- `L1` Exercises

**ZH 11 条**

- `L3` 4.1线性回归
- `L3` 4.2梯度下降
- `L2` 收敛速度
- `L3` 4.3多项式回归
- `L3` 4.4学习曲线
- `L2` 偏差/方差权衡
- `L3` 方差
- `L3` 4.5正则化线性模型
- `L3` 4.6逻辑回归
- `L2` 交叉熵
- `L3` 4.7练习题

### [第5章] Chapter 5. Support Vector Machines　／　第5章 支持向量机

**EN 12 条**

- `L1` Linear SVM Classification
- `L2` Soft Margin Classification
- `L1` Nonlinear SVM Classification
- `L2` Polynomial Kernel
- `L2` Similarity Features
- `L2` Gaussian RBF Kernel
- `L2` SVM Classes and Computational Complexity
- `L1` SVM Regression
- `L1` Under the Hood of Linear SVM Classifiers
- `L1` The Dual Problem
- `L2` Kernelized SVMs
- `L1` Exercises

**ZH 9 条**

- `L3` 5.1线性SVM分类
- `L2` 软间隔分类
- `L3` 5.2非线性SVM分类
- `L3` 5.3 SVM回归
- `L3` 5.4线性SVM分类器的工作原理
- `L3` 5.5对偶问题
- `L2` 核化SVM
- `L2` Mercer定理
- `L3` 5.6练习题

### [第6章] Chapter 6. Decision Trees　／　第6章 决策树

**EN 11 条**

- `L1` Training and Visualizing a Decision Tree
- `L1` Making Predictions
- `L1` Estimating Class Probabilities
- `L1` The CART Training Algorithm
- `L1` Computational Complexity
- `L1` Gini Impurity or Entropy?
- `L1` Regularization Hyperparameters
- `L1` Regression
- `L1` Sensitivity to Axis Orientation
- `L1` Decision Trees Have a High Variance
- `L1` Exercises

**ZH 11 条**

- `L3` 6.1训练和可视化决策树
- `L3` 6.2做出预测
- `L3` 6.3估计类概率
- `L3` 6.4 CART训练算法
- `L3` 6.5计算复杂度
- `L3` 6.6基尼杂质或熵
- `L3` 6.7正则化超参数
- `L3` 6.8回归
- `L3` 6.9对轴方向的敏感性
- `L3` 6.10决策树具有高方差
- `L3` 6.11练习题

### [第7章] Chapter 7. Ensemble Learning and Random Forests　／　第7章 集成学习和随机森林

**EN 14 条**

- `L1` Voting Classifiers
- `L1` Bagging and Pasting
- `L2` Bagging and Pasting in Scikit-Learn
- `L2` Out-of-Bag Evaluation
- `L2` Random Patches and Random Subspaces
- `L1` Random Forests
- `L2` Extra-Trees
- `L2` Feature Importance
- `L1` Boosting
- `L2` AdaBoost
- `L2` Gradient Boosting
- `L2` Histogram-Based Gradient Boosting
- `L1` Stacking
- `L1` Exercises

**ZH 6 条**

- `L3` 7.1投票分类器
- `L3` 7.2 bagging和pasting
- `L3` 7.3随机森林
- `L3` 7.4提升法
- `L3` 7.5堆叠法
- `L3` 7.6练习题

### [第8章] Chapter 8. Dimensionality Reduction　／　第8章 降维

**EN 18 条**

- `L1` The Curse of Dimensionality
- `L1` Main Approaches for Dimensionality Reduction
- `L2` Projection
- `L2` Manifold Learning
- `L1` PCA
- `L2` Preserving the Variance
- `L2` Principal Components
- `L2` Projecting Down to d Dimensions
- `L2` Using Scikit-Learn
- `L2` Explained Variance Ratio
- `L2` Choosing the Right Number of Dimensions
- `L2` PCA for Compression
- `L2` Randomized PCA
- `L2` Incremental PCA
- `L1` Random Projection
- `L1` LLE
- `L1` Other Dimensionality Reduction Techniques
- `L1` Exercises

**ZH 7 条**

- `L3` 8.1维度的诅咒
- `L3` 8.2降维的主要方法
- `L3` 8.3 PCA
- `L3` 8.4随机投影
- `L3` 8.5 LLE
- `L3` 8.6其他降维技术
- `L3` 8.7练习题

### [第9章] Chapter 9. Unsupervised Learning Techniques　／　第9章 无监督学习技术

**EN 17 条**

- `L1` Clustering Algorithms: k-means and DBSCAN
- `L2` k-means
- `L3` The k-means algorithm
- `L3` Centroid initialization methods
- `L3` Accelerated k-means and mini-batch k-means
- `L3` Finding the optimal number of clusters
- `L2` Limits of k-means
- `L2` Using Clustering for Image Segmentation
- `L2` Using Clustering for Semi-Supervised Learning
- `L2` DBSCAN
- `L2` Other Clustering Algorithms
- `L1` Gaussian Mixtures
- `L2` Using Gaussian Mixtures for Anomaly Detection
- `L2` Selecting the Number of Clusters
- `L2` Bayesian Gaussian Mixture Models
- `L2` Other Algorithms for Anomaly and Novelty Detection
- `L1` Exercises

**ZH 11 条**

- `L3` 聚类
- `L3` 9.1聚类算法：k均值和DBSCAN
- `L3` 降维技术
- `L2` k均值算法
- `L2` 质心初始化方法
- `L2` 加速的k均值和小批量k均值
- `L2` 寻找最佳集群数
- `L2` 主动学习
- `L3` 9.2高斯混合模型
- `L2` 似然函数
- `L3` 9.3练习题

### [第2部] Part II. Neural Networks and Deep Learning　／　第二部分

**EN 0 条**


**ZH 1 条**

- `L1` 神经网络与深度学习

### [第10章] Chapter 10. Introduction to Artificial Neural Networks with Keras　／　第10章 Keras人工神经网络简介

**EN 25 条**

- `L1` From Biological to Artificial Neurons
- `L2` Biological Neurons
- `L2` Logical Computations with Neurons
- `L2` The Perceptron
- `L2` The Multilayer Perceptron and Backpropagation
- `L2` Regression MLPs
- `L2` Classification MLPs
- `L1` Implementing MLPs with Keras
- `L2` Building an Image Classifier Using the Sequential API
- `L3` Using Keras to load the dataset
- `L3` Creating the model using the sequential API
- `L3` Compiling the model
- `L3` Training and evaluating the model
- `L3` Using the model to make predictions
- `L2` Building a Regression MLP Using the Sequential API
- `L2` Building Complex Models Using the Functional API
- `L2` Using the Subclassing API to Build Dynamic Models
- `L2` Saving and Restoring a Model
- `L2` Using Callbacks
- `L2` Using TensorBoard for Visualization
- `L1` Fine-Tuning Neural Network Hyperparameters
- `L2` Number of Hidden Layers
- `L2` Number of Neurons per Hidden Layer
- `L2` Learning Rate, Batch Size, and Other Hyperparameters
- `L1` Exercises

**ZH 11 条**

- `L3` 10.1从生物神经元到人工神经元
- `L3` 10.2使用Keras实现MLP
- `L2` 使用Keras加载数据集
- `L2` 使用顺序API创建模型
- `L2` 编译模型
- `L2` 训练和评估模型
- `L2` 使用模型进行预测
- `L3` 10.3微调神经网络超参数
- `L3` 学习率
- `L3` 优化器
- `L3` 10.4练习题

### [第11章] Chapter 11. Training Deep Neural Networks　／　第11章 训练深度神经网络

**EN 30 条**

- `L1` The Vanishing/Exploding Gradients Problems
- `L2` Glorot and He Initialization
- `L2` Better Activation Functions
- `L3` Leaky ReLU
- `L3` ELU and SELU
- `L3` GELU, Swish, and Mish
- `L2` Batch Normalization
- `L3` Implementing batch normalization with Keras
- `L2` Gradient Clipping
- `L1` Reusing Pretrained Layers
- `L2` Transfer Learning with Keras
- `L2` Unsupervised Pretraining
- `L2` Pretraining on an Auxiliary Task
- `L1` Faster Optimizers
- `L2` Momentum
- `L2` Nesterov Accelerated Gradient
- `L2` AdaGrad
- `L2` RMSProp
- `L2` Adam
- `L2` AdaMax
- `L2` Nadam
- `L2` AdamW
- `L1` Learning Rate Scheduling
- `L1` Avoiding Overfitting Through Regularization
- `L2` ℓ1 and ℓ2 Regularization
- `L2` Dropout
- `L2` Monte Carlo (MC) Dropout
- `L2` Max-Norm Regularization
- `L1` Summary and Practical Guidelines
- `L1` Exercises

**ZH 11 条**

- `L3` 11.1梯度消失和梯度爆炸问题
- `L2` leaky ReLU
- `L2` ELU和SELU
- `L2` 用Keras实现批量归一化
- `L3` 11.2重用预训练层
- `L3` 11.3更快的优化器
- `L2` 训练稀疏模型
- `L3` 11.4学习率调度
- `L3` 11.5通过正则化避免过拟合
- `L3` 11.6总结和实用指南
- `L3` 11.7练习题

### [第12章] Chapter 12. Custom Models and Training with TensorFlow　／　第12章 使用TensorFlow自定义模型和训练

**EN 21 条**

- `L1` A Quick Tour of TensorFlow
- `L1` Using TensorFlow like NumPy
- `L2` Tensors and Operations
- `L2` Tensors and NumPy
- `L2` Type Conversions
- `L2` Variables
- `L2` Other Data Structures
- `L1` Customizing Models and Training Algorithms
- `L2` Custom Loss Functions
- `L2` Saving and Loading Models That Contain Custom Components
- `L2` Custom Activation Functions, Initializers, Regularizers, and Constraints
- `L2` Custom Metrics
- `L2` Custom Layers
- `L2` Custom Models
- `L2` Losses and Metrics Based on Model Internals
- `L2` Computing Gradients Using Autodiff
- `L2` Custom Training Loops
- `L1` TensorFlow Functions and Graphs
- `L2` AutoGraph and Tracing
- `L2` TF Function Rules
- `L1` Exercises

**ZH 5 条**

- `L3` 12.1 TensorFlow快速浏览
- `L3` 12.2像使用NumPy一样使用TensorFlow
- `L3` 12.3自定义模型和训练算法
- `L3` 12.4 TensorFlow函数和图
- `L3` 12.5练习题

### [第13章] Chapter 13. Loading and Preprocessing Data with TensorFlow　／　第13章 使用TensorFlow加载和预处理数据

**EN 26 条**

- `L1` The tf.data API
- `L2` Chaining Transformations
- `L2` Shuffling the Data
- `L2` Interleaving Lines from Multiple Files
- `L2` Preprocessing the Data
- `L2` Putting Everything Together
- `L2` Prefetching
- `L2` Using the Dataset with Keras
- `L1` The TFRecord Format
- `L2` Compressed TFRecord Files
- `L2` A Brief Introduction to Protocol Buffers
- `L2` TensorFlow Protobufs
- `L2` Loading and Parsing Examples
- `L2` Handling Lists of Lists Using the SequenceExample Protobuf
- `L1` Keras Preprocessing Layers
- `L2` The Normalization Layer
- `L2` The Discretization Layer
- `L2` The CategoryEncoding Layer
- `L2` The StringLookup Layer
- `L2` The Hashing Layer
- `L2` Encoding Categorical Features Using Embeddings
- `L2` Text Preprocessing
- `L2` Using Pretrained Language Model Components
- `L2` Image Preprocessing Layers
- `L1` The TensorFlow Datasets Project
- `L1` Exercises

**ZH 6 条**

- `L3` 13.1 tf.data API
- `L3` 13.2 TFRecord格式
- `L3` 13.3 Keras预处理层
- `L2` 词嵌入
- `L3` 13.4 TensorFlow数据集项目
- `L3` 13.5练习题

### [第14章] Chapter 14. Deep Computer Vision Using Convolutional Neural Networks　／　第14章 使用卷积神经网络进行深度计算机视觉

**EN 28 条**

- `L1` The Architecture of the Visual Cortex
- `L1` Convolutional Layers
- `L2` Filters
- `L2` Stacking Multiple Feature Maps
- `L2` Implementing Convolutional Layers with Keras
- `L2` Memory Requirements
- `L1` Pooling Layers
- `L1` Implementing Pooling Layers with Keras
- `L1` CNN Architectures
- `L2` LeNet-5
- `L2` AlexNet
- `L2` GoogLeNet
- `L2` VGGNet
- `L2` ResNet
- `L2` Xception
- `L2` SENet
- `L2` Other Noteworthy Architectures
- `L2` Choosing the Right CNN Architecture
- `L1` Implementing a ResNet-34 CNN Using Keras
- `L1` Using Pretrained Models from Keras
- `L1` Pretrained Models for Transfer Learning
- `L1` Classification and Localization
- `L1` Object Detection
- `L2` Fully Convolutional Networks
- `L2` You Only Look Once
- `L1` Object Tracking
- `L1` Semantic Segmentation
- `L1` Exercises

**ZH 16 条**

- `L3` 14.1视觉皮层的结构
- `L3` 14.2卷积层
- `L3` 14.3池化层
- `L3` 14.4使用Keras实现池化层
- `L3` 14.5 CNN架构
- `L2` 数据增强
- `L3` 14.6使用Keras实现ResNet-34 CNN
- `L3` 14.7使用Keras的预训练模型
- `L3` 14.8使用预训练模型进行迁移学习
- `L3` 14.9分类和定位
- `L3` 14.10物体检测
- `L2` 均值平均精度（mAP）
- `L3` 14.11物体跟踪
- `L3` 14.12语义分割
- `L2` 其他Keras卷积层
- `L3` 14.13练习题

### [第15章] Chapter 15. Processing Sequences Using RNNs and CNNs　／　第15章 使用RNN和CNN处理序列

**EN 21 条**

- `L1` Recurrent Neurons and Layers
- `L2` Memory Cells
- `L2` Input and Output Sequences
- `L1` Training RNNs
- `L1` Forecasting a Time Series
- `L2` The ARMA Model Family
- `L2` Preparing the Data for Machine Learning Models
- `L2` Forecasting Using a Linear Model
- `L2` Forecasting Using a Simple RNN
- `L2` Forecasting Using a Deep RNN
- `L2` Forecasting Multivariate Time Series
- `L2` Forecasting Several Time Steps Ahead
- `L2` Forecasting Using a Sequence-to-Sequence Model
- `L1` Handling Long Sequences
- `L2` Fighting the Unstable Gradients Problem
- `L2` Tackling the Short-Term Memory Problem
- `L3` LSTM cells
- `L3` GRU cells
- `L3` Using 1D convolutional layers to process sequences
- `L3` WaveNet
- `L1` Exercises

**ZH 9 条**

- `L3` 15.1循环神经元和层
- `L3` 15.2训练RNN
- `L3` 15.3预测时间序列
- `L3` 15.4处理长序列
- `L2` LSTM单元
- `L2` GRU单元
- `L2` 使用一维卷积层处理序列
- `L2` WaveNet
- `L3` 15.5练习题

### [第16章] Chapter 16. Natural Language Processing with RNNs and Attention　／　第16章 基于RNN和注意力机制的自然语言处理

**EN 19 条**

- `L1` Generating Shakespearean Text Using a Character RNN
- `L2` Creating the Training Dataset
- `L2` Building and Training the Char-RNN Model
- `L2` Generating Fake Shakespearean Text
- `L2` Stateful RNN
- `L1` Sentiment Analysis
- `L2` Masking
- `L2` Reusing Pretrained Embeddings and Language Models
- `L1` An Encoder–Decoder Network for Neural Machine Translation
- `L2` Bidirectional RNNs
- `L2` Beam Search
- `L1` Attention Mechanisms
- `L2` Attention Is All You Need: The Original Transformer Architecture
- `L3` Positional encodings
- `L3` Multi-head attention
- `L1` An Avalanche of Transformer Models
- `L1` Vision Transformers
- `L1` Hugging Face’s Transformers Library
- `L1` Exercises

**ZH 13 条**

- `L3` 16.1使用字符RNN生成莎士比亚文本
- `L3` 16.2情感分析
- `L3` 16.3用于神经机器翻译的编码器-解码器网络
- `L2` 优化输出层
- `L3` 16.4注意力机制
- `L2` 位置编码
- `L2` 多头注意力
- `L3` 16.5 Transformer模型的雪崩
- `L3` 16.6视觉Transformer
- `L2` 可解释性
- `L3` 16.7 Hugging Face的Transformer库
- `L2` 偏见和公平
- `L3` 16.8练习题

### [第17章] Chapter 17. Autoencoders, GANs, and Diffusion Models　／　第17章 自动编码器、GAN和扩散模型

**EN 21 条**

- `L1` Efficient Data Representations
- `L1` Performing PCA with an Undercomplete Linear Autoencoder
- `L1` Stacked Autoencoders
- `L2` Implementing a Stacked Autoencoder Using Keras
- `L2` Visualizing the Reconstructions
- `L2` Visualizing the Fashion MNIST Dataset
- `L2` Unsupervised Pretraining Using Stacked Autoencoders
- `L2` Tying Weights
- `L2` Training One Autoencoder at a Time
- `L1` Convolutional Autoencoders
- `L1` Denoising Autoencoders
- `L1` Sparse Autoencoders
- `L1` Variational Autoencoders
- `L1` Generating Fashion MNIST Images
- `L1` Generative Adversarial Networks
- `L2` The Difficulties of Training GANs
- `L2` Deep Convolutional GANs
- `L2` Progressive Growing of GANs
- `L2` StyleGANs
- `L1` Diffusion Models
- `L1` Exercises

**ZH 11 条**

- `L3` 17.1有效的数据表示
- `L3` 17.2使用不完备的线性自动编码器执行PCA
- `L3` 17.3堆叠式自动编码器
- `L3` 17.4卷积自动编码器
- `L3` 17.5去噪自动编码器
- `L3` 17.6稀疏自动编码器
- `L3` 17.7变分自动编码器
- `L3` 17.8生成Fashion MNIST图像
- `L3` 17.9生成对抗网络
- `L3` 17.10扩散模型
- `L3` 17.11练习题

### [第18章] Chapter 18. Reinforcement Learning　／　第18章 强化学习

**EN 19 条**

- `L1` Learning to Optimize Rewards
- `L1` Policy Search
- `L1` Introduction to OpenAI Gym
- `L1` Neural Network Policies
- `L1` Evaluating Actions: The Credit Assignment Problem
- `L1` Policy Gradients
- `L1` Markov Decision Processes
- `L1` Temporal Difference Learning
- `L1` Q-Learning
- `L2` Exploration Policies
- `L2` Approximate Q-Learning and Deep Q-Learning
- `L1` Implementing Deep Q-Learning
- `L1` Deep Q-Learning Variants
- `L2` Fixed Q-value Targets
- `L2` Double DQN
- `L2` Prioritized Experience Replay
- `L2` Dueling DQN
- `L1` Overview of Some Popular RL Algorithms
- `L1` Exercises

**ZH 13 条**

- `L3` 18.1学习优化奖励
- `L3` 18.2策略搜索
- `L3` 18.3 OpenAI Gym介绍
- `L3` 18.4神经网络策略
- `L3` 18.5评估动作：信用分配问题
- `L3` 18.6策略梯度
- `L3` 18.7马尔可夫决策过程
- `L3` 18.8时序差分学习
- `L3` 18.9 Q学习
- `L3` 18.10实现深度Q学习
- `L3` 18.11深度Q学习的变体
- `L3` 18.12一些流行的RL算法概述
- `L3` 18.13练习题

### [第19章] Chapter 19. Training and Deploying TensorFlow Models at Scale　／　第19章 大规模训练和部署TensorFlow模型

**EN 31 条**

- `L1` Serving a TensorFlow Model
- `L2` Using TensorFlow Serving
- `L3` Exporting SavedModels
- `L3` Installing and starting TensorFlow Serving
- `L3` Querying TF Serving through the REST API
- `L3` Querying TF Serving through the gRPC API
- `L3` Deploying a new model version
- `L2` Creating a Prediction Service on Vertex AI
- `L2` Running Batch Prediction Jobs on Vertex AI
- `L1` Deploying a Model to a Mobile or Embedded Device
- `L1` Running a Model in a Web Page
- `L1` Using GPUs to Speed Up Computations
- `L2` Getting Your Own GPU
- `L2` Managing the GPU RAM
- `L2` Placing Operations and Variables on Devices
- `L2` Parallel Execution Across Multiple Devices
- `L1` Training Models Across Multiple Devices
- `L2` Model Parallelism
- `L2` Data Parallelism
- `L3` Data parallelism using the mirrored strategy
- `L3` Data parallelism with centralized parameters
- `L4` Synchronous updates
- `L4` Asynchronous updates
- `L3` Bandwidth saturation
- `L2` Training at Scale Using the Distribution Strategies API
- `L2` Training a Model on a TensorFlow Cluster
- `L2` Running Large Training Jobs on Vertex AI
- `L2` Hyperparameter Tuning on Vertex AI
- `L1` Exercises
- `L1` Thank You!
- `L1` —Aurélien Géron

**ZH 18 条**

- `L3` 19.1为TensorFlow模型提供服务
- `L2` 导出SavedModel
- `L2` 安装和启动TF Serving
- `L2` 在Docker容器中运行TF服务
- `L2` 通过REST API查询TF Serving
- `L2` 通过gRPC API查询TF Serving
- `L2` 部署新的模型版本
- `L2` Google Cloud CLI和Shell
- `L2` GCP上的身份验证和授权
- `L3` 19.2将模型部署到移动设备或嵌入式设备
- `L3` 19.3在Web页面中运行模型
- `L3` 19.4使用GPU加速计算
- `L3` 19.5跨多个设备训练模型
- `L2` 使用镜像策略的数据并行
- `L2` 集中参数的数据并行
- `L2` 带宽饱和
- `L3` 19.6练习题
- `L3` 致读者

### [附录A] Appendix A. Machine Learning Project Checklist　／　附录A

**EN 8 条**

- `L1` Frame the Problem and Look at the Big Picture
- `L1` Get the Data
- `L1` Explore the Data
- `L1` Prepare the Data
- `L1` Shortlist Promising Models
- `L1` Fine-Tune the System
- `L1` Present Your Solution
- `L1` Launch!

**ZH 8 条**

- `L1` 机器学习项目清单
- `L3` 获取数据
- `L2` 探索数据
- `L3` 准备数据
- `L2` 探索模型
- `L2` 微调系统
- `L2` 展示解决方案
- `L2` 启动系统

### [附录B] Appendix B. Autodiff　／　附录B

**EN 4 条**

- `L1` Manual Differentiation
- `L1` Finite Difference Approximation
- `L1` Forward-Mode Autodiff
- `L1` Reverse-Mode Autodiff

**ZH 5 条**

- `L1` 自动微分
- `L2` 手动微分
- `L2` 有限差分近似
- `L2` 前向模式自动微分
- `L2` 反向模式自动微分

### [附录C] Appendix C. Special Data Structures　／　附录C

**EN 6 条**

- `L1` Strings
- `L1` Ragged Tensors
- `L1` Sparse Tensors
- `L1` Tensor Arrays
- `L1` Sets
- `L1` Queues

**ZH 7 条**

- `L1` 特殊数据结构
- `L2` 字符串
- `L2` 不规则张量
- `L2` 稀疏张量
- `L2` 张量数组
- `L2` 集合
- `L2` 队列

### [附录D] Appendix D. TensorFlow Graphs　／　附录D

**EN 6 条**

- `L1` TF Functions and Concrete Functions
- `L1` Exploring Function Definitions and Graphs
- `L1` A Closer Look at Tracing
- `L1` Using AutoGraph to Capture Control Flow
- `L1` Handling Variables and Other Resources in TF Functions
- `L1` Using TF Functions with Keras (or Not)

**ZH 7 条**

- `L1` TensorFlow图
- `L2` TF函数和具体函数
- `L2` 探索函数定义和函数图
- `L2` 仔细查看跟踪
- `L2` 使用AutoGraph捕获控制流
- `L2` 在TF函数中处理变量和其他资源
- `L2` 将TF函数用于Keras

## 汇总

- 单元：EN 26 / ZH 26（章 EN 19 / ZH 19）
- 小节条目：EN 446 / ZH 250
- **带编号小节**（两侧可直接按编号配对）：EN 0 / ZH 142；**编号相同 0 条**
- ZH 有编号、EN 无：142 条 → 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 10.1, 10.2, 10.3, 10.4, 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.7, 12.1, 12.2
