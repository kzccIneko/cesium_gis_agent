(function (global) {
  "use strict";

  /**
   * SlopeAspectTerrainModule
   *
   * 采用 D8 流向 + 汇流累积提取山谷线与山脊线：
   * - 正向流向/汇流：提取山谷
   * - 反向流向/汇流：提取山脊
   */
  var TerrainModule = {
    /**
     * 山脊山谷提取主流程。
     *
     * 输入：this.slopeCostGrid（含每格高程）
     * 输出：在 Cesium 中绘制红/蓝点，并把中间结果写入 this.flowAccumulation。
     */
    Ridge_Valley_Analysis: function () {
      if (!this.slopeCostGrid || this.slopeCostGrid.length === 0) {
        alert('请先计算区域坡度！');
        return;
      }
      console.time('山脊线山谷线提取');

      var rows = this.slopeCostGrid.length;
      var cols = this.slopeCostGrid[0].length;
      this.valleyThresholdRatio = $('#valleyThresholdRatio').val();
      this.ridgeThresholdRatio = $('#ridgeThresholdRatio').val();

      var DEM = new Array(rows);
      for (var i = 0; i < rows; i++) {
        DEM[i] = new Array(cols).fill(0);
      }

      for (var i2 = 0; i2 < rows; i2++) {
        for (var j2 = 0; j2 < cols; j2++) {
          var cell = this.slopeCostGrid[i2][j2];
          if (cell.degreeCoordinate !== undefined) {
            DEM[i2][j2] = Number(cell.degreeCoordinate[2]);
          } else {
            DEM[i2][j2] = Number.NaN;
          }
        }
      }

      var flowDir = new Array(rows);
      for (var i3 = 0; i3 < rows; i3++) {
        flowDir[i3] = new Array(cols).fill(0);
      }

      // D8 八邻域方向（顺时针）
      var directions = [
        [0, 1],
        [1, 1],
        [1, 0],
        [1, -1],
        [0, -1],
        [-1, -1],
        [-1, 0],
        [-1, 1],
      ];
      // D8 编码值，对应 directions 中的 8 个方向
      var dirCodes = [1, 2, 4, 8, 16, 32, 64, 128];

      for (var i4 = 0; i4 < rows; i4++) {
        for (var j4 = 0; j4 < cols; j4++) {
          var z = DEM[i4][j4];
          if (!isFinite(z)) continue;

          var maxDrop = 0;
          var flowDirCode = 0;

          for (var d = 0; d < 8; d++) {
            var ni = i4 + directions[d][0];
            var nj = j4 + directions[d][1];
            if (ni < 0 || ni >= rows || nj < 0 || nj >= cols) continue;

            var nz = DEM[ni][nj];
            if (!isFinite(nz)) continue;

            var drop = z - nz;
            if (drop > maxDrop) {
              maxDrop = drop;
              flowDirCode = dirCodes[d];
            }
          }

          flowDir[i4][j4] = flowDirCode;
        }
      }

      var flowAcc = new Array(rows);
      for (var i5 = 0; i5 < rows; i5++) {
        flowAcc[i5] = new Array(cols).fill(1);
      }

      var cellList = [];
      for (var i6 = 0; i6 < rows; i6++) {
        for (var j6 = 0; j6 < cols; j6++) {
          var z2 = DEM[i6][j6];
          if (isFinite(z2)) {
            cellList.push({ i: i6, j: j6, z: z2 });
          }
        }
      }
      cellList.sort(function (a, b) {
        return b.z - a.z;
      });

      for (var idx = 0; idx < cellList.length; idx++) {
        var cell2 = cellList[idx];
        var i7 = cell2.i;
        var j7 = cell2.j;
        var dir = flowDir[i7][j7];
        if (dir === 0) continue;

        var targetI = i7;
        var targetJ = j7;
        for (var d2 = 0; d2 < 8; d2++) {
          if (dirCodes[d2] === dir) {
            targetI = i7 + directions[d2][0];
            targetJ = j7 + directions[d2][1];
            break;
          }
        }

        if (targetI >= 0 && targetI < rows && targetJ >= 0 && targetJ < cols) {
          flowAcc[targetI][targetJ] += flowAcc[i7][j7];
        }
      }

      var revFlowDir = new Array(rows);
      for (var i8 = 0; i8 < rows; i8++) {
        revFlowDir[i8] = new Array(cols).fill(0);
      }

      for (var i9 = 0; i9 < rows; i9++) {
        for (var j9 = 0; j9 < cols; j9++) {
          var z3 = DEM[i9][j9];
          if (!isFinite(z3)) continue;

          var maxRise = 0;
          var revFlowDirCode = 0;

          for (var d3 = 0; d3 < 8; d3++) {
            var ni2 = i9 + directions[d3][0];
            var nj2 = j9 + directions[d3][1];
            if (ni2 < 0 || ni2 >= rows || nj2 < 0 || nj2 >= cols) continue;

            var nz2 = DEM[ni2][nj2];
            if (!isFinite(nz2)) continue;

            var rise = nz2 - z3;
            if (rise > maxRise) {
              maxRise = rise;
              revFlowDirCode = dirCodes[d3];
            }
          }

          revFlowDir[i9][j9] = revFlowDirCode;
        }
      }

      var revFlowAcc = new Array(rows);
      for (var i10 = 0; i10 < rows; i10++) {
        revFlowAcc[i10] = new Array(cols).fill(1);
      }

      cellList.sort(function (a, b) {
        return a.z - b.z;
      });

      for (var idx2 = 0; idx2 < cellList.length; idx2++) {
        var cell3 = cellList[idx2];
        var i11 = cell3.i;
        var j11 = cell3.j;
        var dir2 = revFlowDir[i11][j11];
        if (dir2 === 0) continue;

        var targetI2 = i11;
        var targetJ2 = j11;
        for (var d4 = 0; d4 < 8; d4++) {
          if (dirCodes[d4] === dir2) {
            targetI2 = i11 + directions[d4][0];
            targetJ2 = j11 + directions[d4][1];
            break;
          }
        }

        if (targetI2 >= 0 && targetI2 < rows && targetJ2 >= 0 && targetJ2 < cols) {
          revFlowAcc[targetI2][targetJ2] += revFlowAcc[i11][j11];
        }
      }

      var maxFlowAcc = 0;
      var maxRevFlowAcc = 0;
      var maxHeight = -Infinity;
      var minHeight = Infinity;
      for (var i12 = 0; i12 < rows; i12++) {
        for (var j12 = 0; j12 < cols; j12++) {
          if (isFinite(DEM[i12][j12])) {
            if (flowAcc[i12][j12] > maxFlowAcc) maxFlowAcc = flowAcc[i12][j12];
            if (revFlowAcc[i12][j12] > maxRevFlowAcc) maxRevFlowAcc = revFlowAcc[i12][j12];
          }
        }
      }

      minHeight = this.arrayMinMax(DEM.flat().filter(Number.isFinite))[0];
      maxHeight = this.arrayMinMax(DEM.flat().filter(Number.isFinite))[1];
      console.log('DEM', DEM, '区域最小高程:', minHeight, '区域最大高程:', maxHeight);

      var HeightRatio = 0;
      var valleyThreshold = maxFlowAcc * this.valleyThresholdRatio;
      var ridgeThreshold = maxRevFlowAcc * this.ridgeThresholdRatio;

      console.log('汇流累积最大值:', maxFlowAcc, '山谷线阈值:', valleyThreshold);
      console.log('反向汇流累积最大值:', maxRevFlowAcc, '山脊线阈值:', ridgeThreshold);

      var valleyPoints = [];
      for (var i13 = 0; i13 < rows; i13++) {
        for (var j13 = 0; j13 < cols; j13++) {
          HeightRatio = (DEM[i13][j13] - minHeight) / (maxHeight - minHeight);
          if (flowAcc[i13][j13] >= valleyThreshold * HeightRatio && isFinite(DEM[i13][j13])) {
            var c1 = this.slopeCostGrid[i13][j13];
            if (c1 && c1.Cartesian) valleyPoints.push(c1.Cartesian);
          }
        }
      }

      var ridgePoints = [];
      for (var i14 = 0; i14 < rows; i14++) {
        for (var j14 = 0; j14 < cols; j14++) {
          HeightRatio = (DEM[i14][j14] - minHeight) / (maxHeight - minHeight);
          if (revFlowAcc[i14][j14] >= ridgeThreshold * HeightRatio && isFinite(DEM[i14][j14])) {
            var c2 = this.slopeCostGrid[i14][j14];
            if (c2 && c2.Cartesian) ridgePoints.push(c2.Cartesian);
          }
        }
      }

      console.log('提取山谷线点数:', valleyPoints.length);
      console.log('提取山脊线点数:', ridgePoints.length);

      var viewer = this.viewer;
      if (this.ridgeValleyEntities) {
        this.ridgeValleyEntities.forEach(function (ent) {
          viewer.entities.remove(ent);
        });
      }
      this.ridgeValleyEntities = [];

      if (valleyPoints.length > 0) {
        valleyPoints.forEach(function (pos) {
          var entity = viewer.entities.add({
            position: pos,
            point: {
              pixelSize: 6,
              color: Cesium.Color.BLUE,
              heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
            },
          });
          entity.isRidgeValley = true;
          this.ridgeValleyEntities.push(entity);
        }, this);
        console.log('✓ 已绘制山谷线（蓝色）');
      }

      if (ridgePoints.length > 0) {
        ridgePoints.forEach(function (pos) {
          var entity = viewer.entities.add({
            position: pos,
            point: {
              pixelSize: 6,
              color: Cesium.Color.RED,
              heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
            },
          });
          entity.isRidgeValley = true;
          this.ridgeValleyEntities.push(entity);
        }, this);
        console.log('✓ 已绘制山脊线（红色）');
      }

      this.flowAccumulation = {
        DEM: DEM,
        flowDir: flowDir,
        flowAcc: flowAcc,
        revFlowDir: revFlowDir,
        revFlowAcc: revFlowAcc,
        valleyPoints: valleyPoints,
        ridgePoints: ridgePoints,
      };

      console.timeEnd('山脊线山谷线提取');
      alert('提取完成！\n山谷线（蓝色）: ' + valleyPoints.length + ' 点\n山脊线（红色）: ' + ridgePoints.length + ' 点');
    },
  };

  global.SlopeAspectTerrainModule = TerrainModule;
})(window);
