  // AHP 层次分析法计算权重与一致性检验
  SlopeAspect.prototype.AHPanalysistest = function(){
    // 从单个输入框读取逗号分隔的权重值
    const weightsInput = $('#WeightsInput').val().trim();

    // 解析输入：分割、过滤空值、转换为数字
    this.weights = (weightsInput
      .split(/[,，\s]+/)  // 支持中英文逗号和空格分隔
      .map(v => v.trim())
      .filter(v => v.length > 0)
      .map(v => parseFloat(v))
      .filter(v => !isNaN(v) && v > 0)) || (this.weights);  // 只保留正数
console.log('解析后的权重值:', this.weights);
    // 校验输入
    if (this.weights.length < 3) {
      alert('请至少输入3个权重值！当前输入: ' + this.weights.length + '个');
      console.error('权重数量不足，至少需要3个，当前:', this.weights);
      return;
    }
    if (this.weights.length > 15) {
      alert('权重数量不能超过15个！当前输入: ' + this.weights.length + '个\n(AHP一致性检验的RI表最大支持15阶矩阵)');
      console.warn('权重数量过多:', this.weights.length);
      return;
    }

    // 更新 elementC
    this.elementC = this.weights;
    console.log('读取到的权重值:', this.elementC);
    let RM = this.JudgeArray();//判断矩阵
    console.log(RM);
    const results = this.computeAHPWeightsAndConsistency(RM);//计算权重与一致性检验

    console.log('矩阵维度:', results.n);
    console.log('特征向量法权重:', results.weights_eigen);
    console.log('几何平均法权重:', results.weights_geom);
    console.log('最大特征值 λ_max:', results.lambda_max);
    console.log('一致性指标 CI:', results.CI);
    console.log('随机一致性指标 RI:', results.RI);
    console.log('一致性比率 CR:', results.CR);
    console.log('通过一致性检验?', results.consistent ? '是 (CR < 0.1)' : '否 (CR >= 0.1)');
    
    return results;
  }
  // 判断矩阵(目标层元素Ci对应设定重要性值)
  SlopeAspect.prototype.JudgeArray = function(){
    let elementC = this.elementC;
    let RM = [];
    for (let i = 0; i < elementC.length; i++) { 
      RM[i] = []; // 初始化第 i 行
      for (let j = 0; j < elementC.length; j++) { 
          let aij = elementC[i] / elementC[j];// 判断矩阵内元素
          RM[i].push(aij); 
      }
    }
    return RM;
  }
  SlopeAspect.prototype.computeAHPWeightsAndConsistency = function(RM) {
    // ==================== AHP 层次分析法计算权重与一致性检验 ====================
    /**
     * computeAHPWeightsAndConsistency(RM)
     * 输入: RM 为 n×n 的判断矩阵（二维数组）
     * 输出: 包含特征向量法权重、几何平均法权重、最大特征值、CI、CR、一致性结论的对象
     * 
     * 第一部分：计算权重向量
     *   方法1：特征向量法（幂迭代求主特征向量并归一化）
     *   方法2：几何平均法（每行元素相乘开n次方根再归一化）
     * 
     * 第二部分：一致性检验
     *   计算最大特征值 λ_max
     *   计算一致性指标 CI = (λ_max - n) / (n - 1)
     *   计算一致性比率 CR = CI / RI（RI为随机一致性指标）
     *   判断 CR < 0.1 是否成立（成立则矩阵满足一致性要求）
     */
    // ==================== 0. 输入校验与常量定义 ====================
    
    // 校验 RM 是否为方阵
    if (!Array.isArray(RM) || RM.length === 0) {
      throw new Error('AHP: RM 必须是非空的二维数组');
    }
    const n = RM.length; // 矩阵维度（阶数）
    for (let i = 0; i < n; i++) {
      if (!Array.isArray(RM[i]) || RM[i].length !== n) {
        throw new Error('AHP: RM 必须是 n × n 的方阵');
      }
    }

    // RI 表：随机一致性指标（Random Index）
    // 来源于 Saaty 的 AHP 理论，常用于一致性检验
    // 索引对应矩阵阶数 n，n=1和n=2时 RI=0（完全一致）
    const RI_TABLE = {
      1: 0.00, 2: 0.00, 3: 0.58, 4: 0.90, 5: 1.12,
      6: 1.24, 7: 1.32, 8: 1.41, 9: 1.45, 10: 1.49,
      11: 1.51, 12: 1.48, 13: 1.56, 14: 1.57, 15: 1.59
    };
    // 获取当前矩阵阶数对应的 RI 值（若超出表范围则使用近似值 1.59）
    const RI = RI_TABLE[n] !== undefined ? RI_TABLE[n] : 1.59;

    // ==================== 辅助函数定义 ====================

    // 矩阵与向量相乘：计算 y = A * x
    // A: n×n 矩阵，x: n×1 向量，返回 y: n×1 向量
    const matVecMul = (A, x) => {
      const m = A.length;
      const y = new Array(m).fill(0); // 初始化结果向量
      for (let i = 0; i < m; i++) {
        let sum = 0;
        for (let j = 0; j < A[i].length; j++) {
          sum += A[i][j] * x[j]; // 累加第 i 行与 x 的内积
        }
        y[i] = sum;
      }
      return y;
    };

    // 向量归一化（按和归一）：使所有元素之和为 1
    const normalizeSum = (v) => {
      const sum = v.reduce((acc, val) => acc + val, 0); // 计算向量元素总和
      if (sum === 0) return v.map(() => 0); // 避免除零
      return v.map(x => x / sum); // 每个元素除以总和
    };

    // 计算向量的欧几里得范数（2-范数）：||v||₂ = sqrt(Σvᵢ²)
    const norm2 = (v) => {
      return Math.sqrt(v.reduce((acc, val) => acc + val * val, 0));
    };

    // ==================== 第一部分：方法1 - 特征向量法求权重 ====================
    
    // 使用幂迭代（Power Iteration）求主特征向量
    // 原理：对于正互反矩阵，主特征向量对应最大特征值，反映各元素的相对权重
    
    // 初始化：取全 1 向量作为初始特征向量
    let x = new Array(n).fill(1);
    x = normalizeSum(x); // 归一化（和为 1）

    // 幂迭代参数设置
    const maxIter = 1000;        // 最大迭代次数
    const tolerance = 1e-12;     // 收敛容差（残差阈值）
    let lambda = 0;              // 当前近似特征值
    let iter = 0;                // 迭代计数器
    let residual = Infinity;     // 残差（衡量收敛程度）

    // 开始幂迭代循环
    for (iter = 0; iter < maxIter; iter++) {
      // Step 1: 计算 y = A * x（矩阵向量乘法）
      const y = matVecMul(RM, x);

      // Step 2: 计算 Rayleigh 商估计特征值
      // λ ≈ (x^T · y) / (x^T · x)，即 x 与 y 的内积除以 x 的模平方
      const xDotY = x.reduce((acc, xi, idx) => acc + xi * y[idx], 0); // x^T · y
      const xDotX = x.reduce((acc, xi) => acc + xi * xi, 0);          // x^T · x
      const lambda_new = (xDotX === 0) ? 0 : (xDotY / xDotX);

      // Step 3: 归一化 y 作为下一轮的 x
      const y_norm = normalizeSum(y);

      // Step 4: 计算残差 ||y_norm - x||₂（判断是否收敛）
      residual = 0;
      for (let i = 0; i < n; i++) {
        const diff = y_norm[i] - x[i];
        residual += diff * diff;
      }
      residual = Math.sqrt(residual); // 欧几里得距离

      // Step 5: 更新变量准备下一次迭代
      x = y_norm;          // 更新特征向量
      lambda = lambda_new; // 更新特征值

      // Step 6: 判断是否收敛（残差小于容差）
      if (residual < tolerance) {
        iter++; // 记录完成的迭代次数
        break;  // 跳出循环
      }
    }

    // 得到特征向量法的权重向量（x 已归一化，和为 1）
    const weights_eigen = x.slice(); // 复制数组作为最终权重

    // ==================== 计算最大特征值 λ_max ====================
    
    // 更稳健的方法：计算 (A*w)ᵢ / wᵢ 对所有 i 的平均值
    // 原理：对于特征向量 w，有 A*w = λ*w，因此 λ = (A*w)ᵢ / wᵢ
    const Aw = matVecMul(RM, weights_eigen); // 计算 A * w
    let lambda_sum = 0;   // 累加各行的特征值估计
    let lambda_count = 0; // 有效行数（权重非零的行）
    
    for (let i = 0; i < n; i++) {
      const wi = weights_eigen[i];
      // 只对权重非零的元素计算（避免除零）
      if (Math.abs(wi) > 1e-15) {
        lambda_sum += Aw[i] / wi; // λᵢ = (A*w)ᵢ / wᵢ
        lambda_count++;
      }
    }
    
    // 取平均作为最大特征值 λ_max
    const lambda_max = (lambda_count > 0) ? (lambda_sum / lambda_count) : lambda;

    // ==================== 第一部分：方法2 - 几何平均法求权重 ====================
    
    // 原理：每行元素相乘取 n 次方根（即几何平均），再归一化
    // 公式：wᵢ = (∏ⱼ aᵢⱼ)^(1/n) / Σₖ(∏ⱼ aₖⱼ)^(1/n)
    
    const geom = new Array(n).fill(0); // 存储每行的几何平均值
    
    for (let i = 0; i < n; i++) {
      // 为避免浮点下溢/上溢，使用对数和方法
      // 几何平均 = exp( (1/n) * Σ ln(aᵢⱼ) )
      let logSum = 0;
      for (let j = 0; j < n; j++) {
        const aij = RM[i][j];
        // 处理非正值情况（AHP 中不应出现，这里做容错处理）
        if (aij <= 0) {
          logSum += Math.log(Number.EPSILON); // 用极小正数代替
        } else {
          logSum += Math.log(aij); // 累加对数
        }
      }
      // 计算第 i 行的几何平均值：exp(logSum / n)
      geom[i] = Math.exp(logSum / n);
    }
    
    // 归一化几何平均值得到权重向量（和为 1）
    const weights_geom = normalizeSum(geom);

    // ==================== 第二部分：一致性检验 ====================
    
    // Step 1: 计算一致性指标 CI (Consistency Index)
    // 公式：CI = (λ_max - n) / (n - 1)
    // 含义：衡量判断矩阵偏离完全一致性的程度
    const CI = (lambda_max - n) / (n - 1);

    // Step 2: 计算一致性比率 CR (Consistency Ratio)
    // 公式：CR = CI / RI
    // 含义：将 CI 与随机矩阵的平均 CI（即 RI）比较
    const CR = (RI === 0) ? 0 : (CI / RI);

    // Step 3: 判断一致性是否通过
    // 准则：CR < 0.1 则认为矩阵具有满意的一致性
    const consistent = isFinite(CR) ? (CR < 0.1) : false;

    // ==================== 返回计算结果 ====================
    
    return {
      n: n,                           // 矩阵维度（阶数）
      weights_eigen: weights_eigen,   // 特征向量法得到的权重向量（和为 1）
      weights_geom: weights_geom,     // 几何平均法得到的权重向量（和为 1）
      lambda_max: lambda_max,         // 最大特征值 λ_max
      CI: CI,                         // 一致性指标
      RI: RI,                         // 随机一致性指标（查表得到）
      CR: CR,                         // 一致性比率
      consistent: consistent,         // 是否通过一致性检验（CR < 0.1）
      details: {                      // 可选的调试信息
        powerIterIters: iter,         // 幂迭代实际执行次数
        powerIterResidual: residual   // 最终残差
      }
    };
  }