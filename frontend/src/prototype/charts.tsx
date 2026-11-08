import {Fragment, useEffect, useRef, type CSSProperties} from 'react';
import type { Pair, Iead, Density, FullRun } from 'agent';
type Range = {min:number;max:number};
interface ChartOptions { logY?:boolean; threshold?:number; ariaLabel?:string; title?:string; xLabel?:string; yLabel?:string }
// v12.3.1 app.js:905–1116; exact original sample selection, coordinates and rounding.
export function svgChart(points: {x:number;y:number}[], compact: boolean) {
    if (!points || !points.length) return '';
    const width = compact ? 520 : 760;
    const height = compact ? 180 : 230;
    const pad = compact ? 24 : 34;
    const minX = Math.min(...points.map((point) => point.x));
    const maxX = Math.max(...points.map((point) => point.x));
    const maxY = Math.max(...points.map((point) => point.y), 1);
    const xy = points.map((point) => ({
      x: pad + ((point.x - minX) / Math.max(maxX - minX, 1)) * (width - pad * 2),
      y: height - pad - (point.y / maxY) * (height - pad * 2),
    }));
    const path = xy.map((point, index) => `${index ? 'L' : 'M'}${point.x.toFixed(1)} ${point.y.toFixed(1)}`).join(' ');
    const area = `${path} L${xy.at(-1)!.x.toFixed(1)} ${height - pad} L${xy[0].x.toFixed(1)} ${height - pad} Z`;
    return <><svg className="ied-chart-svg" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Ion Energy Distribution 그래프">
      <defs><linearGradient id="chart-fill" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stopColor="#4168e8" stopOpacity=".28"></stop><stop offset="1" stopColor="#4168e8" stopOpacity=".02"></stop></linearGradient></defs>
      <line x1={pad} y1={height - pad} x2={width - pad} y2={height - pad} className="chart-axis"></line>
      <path d={area} fill="url(#chart-fill)"></path><path d={path} className="chart-line"></path>
      {xy.filter((_, index) => index % 4 === 0).map((point,index) => <Fragment key={index}><circle cx={point.x} cy={point.y} r="3" className="chart-point"></circle></Fragment>)}
      <text x={pad} y={height - 6} className="chart-label">{minX} eV</text><text x={width - pad} y={height - 6} textAnchor="end" className="chart-label">{maxX} eV</text>
    </svg></>;
  }

  export function compactNumber(value: number | undefined) {
    if (typeof value !== 'number' || !Number.isFinite(value)) return 'N/A';
    const absolute = Math.abs(value);
    if ((absolute > 0 && absolute < 0.01) || absolute >= 100000) return value.toExponential(2);
    return value.toLocaleString('ko-KR', { maximumFractionDigits: absolute < 10 ? 2 : 1 });
  }

  export function analysisLineChart(points: (Pair | {x:number;y:number})[] | null, options: ChartOptions = {}) {
    const pairs = (points || []).map((point) => Array.isArray(point)
      ? { x: Number(point[0]), y: Number(point[1]) }
      : { x: Number(point.x), y: Number(point.y) })
      .filter((point) => Number.isFinite(point.x) && Number.isFinite(point.y) && (!options.logY || point.y > 0));
    if (!pairs.length) return <><div className="analysis-chart-empty">표시할 실제 수치가 없습니다.</div></>;
    const width = 680;
    const height = 280;
    const pad = { left: 58, right: 20, top: 18, bottom: 44 };
    let minX = Infinity;
    let maxX = -Infinity;
    let minY = Infinity;
    let maxY = -Infinity;
    for (const point of pairs) {
      if (options.logY) point.y = Math.log10(point.y);
      minX = Math.min(minX, point.x);
      maxX = Math.max(maxX, point.x);
      minY = Math.min(minY, point.y);
      maxY = Math.max(maxY, point.y);
    }
    if (!options.logY && minY > 0) minY = 0;
    if (minX === maxX) maxX += 1;
    if (minY === maxY) maxY += 1;
    const plotWidth = width - pad.left - pad.right;
    const plotHeight = height - pad.top - pad.bottom;
    const path = pairs.map((point, index) => {
      const x = pad.left + ((point.x - minX) / (maxX - minX)) * plotWidth;
      const y = pad.top + (1 - (point.y - minY) / (maxY - minY)) * plotHeight;
      return `${index ? 'L' : 'M'}${x.toFixed(1)} ${y.toFixed(1)}`;
    }).join(' ');
    const yTicks = [0, 0.5, 1].map((ratio) => {
      const transformed = maxY - ratio * (maxY - minY);
      const value = options.logY ? 10 ** transformed : transformed;
      const y = pad.top + ratio * plotHeight;
      return <Fragment key={ratio}><line x1={pad.left} y1={y} x2={width - pad.right} y2={y} className="analysis-grid-line"></line><text x={pad.left - 9} y={y + 4} textAnchor="end" className="analysis-axis-label">{compactNumber(value)}</text></Fragment>;
    });
    const thresholdY = options.threshold && options.threshold > 0
      ? pad.top + (1 - ((options.logY ? Math.log10(options.threshold) : options.threshold) - minY) / (maxY - minY)) * plotHeight
      : null;
    const threshold = thresholdY !== null && thresholdY >= pad.top && thresholdY <= height - pad.bottom
      ? <><line x1={pad.left} y1={thresholdY} x2={width - pad.right} y2={thresholdY} className="analysis-threshold"></line><text x={width - pad.right} y={thresholdY - 5} textAnchor="end" className="analysis-threshold-label">strict 1e-8</text></> : '';
    return <><svg className="analysis-line-svg" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={options.ariaLabel || options.title || '실험 수치 그래프'}>
      {yTicks}{threshold}<line x1={pad.left} y1={height - pad.bottom} x2={width - pad.right} y2={height - pad.bottom} className="analysis-axis"></line>
      <line x1={pad.left} y1={pad.top} x2={pad.left} y2={height - pad.bottom} className="analysis-axis"></line>
      <path d={path} className="analysis-line"></path>
      <text x={pad.left} y={height - 17} className="analysis-axis-label">{compactNumber(minX)}</text><text x={width - pad.right} y={height - 17} textAnchor="end" className="analysis-axis-label">{compactNumber(maxX)}</text>
      <text x={width / 2} y={height - 3} textAnchor="middle" className="analysis-axis-title">{options.xLabel || ''}</text>
      <text x="14" y={height / 2} textAnchor="middle" transform={`rotate(-90 14 ${height / 2})`} className="analysis-axis-title">{options.yLabel || ''}</text>
    </svg></>;
  }

  const comparisonColors = ['#4168e8', '#0a8e9b', '#8a5bd7'];

  export function comparisonLineChart(series: {available:boolean;runId:string;points:Pair[]}[], options: ChartOptions = {}) {
    const available = (series || []).filter((item) => item.available && item.points.length);
    if (!available.length) return <><div className="analysis-chart-empty">선택한 후보에 표시할 실제 파형이 없습니다.</div></>;
    const allPoints = available.flatMap((item) => item.points);
    const width = 760;
    const height = 300;
    const pad = { left: 66, right: 24, top: 20, bottom: 46 };
    const minX = Math.min(...allPoints.map((point) => point[0]));
    let maxX = Math.max(...allPoints.map((point) => point[0]));
    let minY = Math.min(...allPoints.map((point) => point[1]));
    let maxY = Math.max(...allPoints.map((point) => point[1]));
    if (minY >= 0) minY = 0;
    if (maxY <= 0) maxY = 0;
    if (minX === maxX) maxX += 1;
    if (minY === maxY) maxY += 1;
    const plotWidth = width - pad.left - pad.right;
    const plotHeight = height - pad.top - pad.bottom;
    const xPosition = (value: number) => pad.left + ((value - minX) / (maxX - minX)) * plotWidth;
    const yPosition = (value: number) => pad.top + (1 - (value - minY) / (maxY - minY)) * plotHeight;
    const grid = [0, 0.5, 1].map((ratio) => {
      const value = maxY - ratio * (maxY - minY);
      const y = pad.top + ratio * plotHeight;
      return <Fragment key={ratio}><line x1={pad.left} y1={y} x2={width - pad.right} y2={y} className="analysis-grid-line"></line><text x={pad.left - 10} y={y + 4} textAnchor="end" className="analysis-axis-label">{compactNumber(value)}</text></Fragment>;
    });
    const paths = available.map((item) => {
      const colorIndex = Math.max(0, (series || []).findIndex((candidate) => candidate.runId === item.runId));
      const path = item.points.map((point, index) => `${index ? 'L' : 'M'}${xPosition(point[0]).toFixed(1)} ${yPosition(point[1]).toFixed(1)}`).join(' ');
      return <Fragment key={item.runId}><path d={path} className="comparison-line" style={{'--series-color':comparisonColors[colorIndex % comparisonColors.length]} as CSSProperties}></path></Fragment>;
    });
    return <><svg className="analysis-line-svg comparison-line-svg" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={options.ariaLabel || '선택 후보 실제 수치 비교 그래프'}>
      {grid}<line x1={pad.left} y1={height - pad.bottom} x2={width - pad.right} y2={height - pad.bottom} className="analysis-axis"></line>
      <line x1={pad.left} y1={pad.top} x2={pad.left} y2={height - pad.bottom} className="analysis-axis"></line>{paths}
      <text x={pad.left} y={height - 18} className="analysis-axis-label">{compactNumber(minX)}</text><text x={width - pad.right} y={height - 18} textAnchor="end" className="analysis-axis-label">{compactNumber(maxX)}</text>
      <text x={width / 2} y={height - 3} textAnchor="middle" className="analysis-axis-title">{options.xLabel || ''}</text>
      <text x="15" y={height / 2} textAnchor="middle" transform={`rotate(-90 15 ${height / 2})`} className="analysis-axis-title">{options.yLabel || ''}</text>
    </svg></>;
  }

  export function positiveRange(values: number[]) {
    let min = Infinity;
    let max = -Infinity;
    (values || []).forEach((value) => {
      if (!Number.isFinite(value) || value <= 0) return;
      min = Math.min(min, value);
      max = Math.max(max, value);
    });
    return min === Infinity ? null : { min, max };
  }

  const emptyHeatColor = 0xf2f5fb;
  function heatColors(min: number, max: number, useLog = true) {
    const start = useLog ? Math.log10(Math.max(min, Number.MIN_VALUE)) : min;
    const end = useLog ? Math.log10(Math.max(max, Number.MIN_VALUE)) : max;
    const span = Math.max(end - start, Number.EPSILON);
    return (value: number) => {
      if (!Number.isFinite(value) || value <= 0) return emptyHeatColor;
      const current = useLog ? Math.log10(value) : value;
      const ratio = Math.max(0, Math.min(1, (current - start) / span));
      const eased = Math.pow(ratio, 0.72);
      const red = Math.round(239 + (34 - 239) * eased);
      const green = Math.round(244 + (76 - 244) * eased);
      const blue = Math.round(255 + (170 - 255) * eased);
      return (red << 16) | (green << 8) | blue;
    };
  }

  function heatColorCss(color: number) {
    return color === emptyHeatColor ? '#f2f5fb' : `rgb(${color >> 16},${(color >> 8) & 255},${color & 255})`;
  }

  export function blueHeatColor(value: number, min: number, max: number, useLog = true) {
    return heatColorCss(heatColors(min, max, useLog)(value));
  }

  const svgCellLimit = 4096;
  const heatmapHeight = 360;
  const heatmapTop = 20;
  const heatmapBottom = 48;
  const heatmapPlotHeight = heatmapHeight - heatmapTop - heatmapBottom;
  type RasterBox = {x:number;y:number;width:number;height:number};

  export function heatmapSampleShape(grid: Iead | Density | null): Pair | null {
    if (!grid) return null;
    return 'angles' in grid ? [grid.angles.length, grid.energies.length] : [grid.rows.length, grid.rows[0]?.[1].length ?? 0];
  }

  // The axes are sorted source coordinates. Draw each cell between its neighbors' midpoints.
  function cellEdges(axis: number[]) {
    if (axis.length < 2) return [0, 1];
    const first = axis[0] - (axis[1] - axis[0]) / 2;
    const last = axis.at(-1)! + (axis.at(-1)! - axis.at(-2)!) / 2;
    return [0, ...axis.slice(1).map((value, index) => (axis[index] + (value - axis[index]) / 2 - first) / (last - first)), 1];
  }

  function rasterEdges(axis: number[], pixels: number) {
    const edges = cellEdges(axis);
    // Keep at least one backing pixel for each original cell, even for closely spaced coordinates.
    for (let index = 1; index < edges.length - 1; index++) {
      edges[index] = Math.max(edges[index - 1] + 1, Math.min(pixels - axis.length + index, Math.round(edges[index] * pixels)));
    }
    edges[edges.length - 1] = pixels;
    return edges;
  }

  function rasterSize(coordinates: number, plotSize: number) {
    return Math.max(coordinates, Math.min(4096, Math.max(coordinates * 2, plotSize * 2)));
  }

  function paintIead(context: CanvasRenderingContext2D, iead: Iead, width: number, height: number, color: (value: number) => number) {
    const xEdges = rasterEdges(iead.energies, width);
    const yEdges = rasterEdges(iead.angles, height);
    const image = context.createImageData(width, height);
    const {data} = image;
    for (let row = 0; row < iead.angles.length; row++) {
      const yStart = height - yEdges[row + 1];
      const yEnd = height - yEdges[row];
      for (let col = 0; col < iead.energies.length; col++) {
        const rgb = color(iead.values[row * iead.energies.length + col]);
        for (let y = yStart; y < yEnd; y++) {
          for (let x = xEdges[col]; x < xEdges[col + 1]; x++) {
            const offset = (y * width + x) * 4;
            data[offset] = rgb >> 16;
            data[offset + 1] = (rgb >> 8) & 255;
            data[offset + 2] = rgb & 255;
            data[offset + 3] = 255;
          }
        }
      }
    }
    context.putImageData(image, 0, 0);
  }

  function densityCell(distances: number[], index: number, maxDistance: number) {
    const distance = distances[index];
    const step = index === distances.length - 1 ? distance - (distances[index - 1] ?? distance) : distances[index + 1] - distance;
    const y = heatmapTop + (1 - distance / maxDistance) * heatmapPlotHeight;
    const height = Math.max(1, step / maxDistance * heatmapPlotHeight);
    return { y: y - height / 2, height: height + 0.5 };
  }

  function HeatmapRaster({grid,box,min,max,maxDistance=1}:{
    grid: Iead | Density; box: RasterBox; min: number; max: number; maxDistance?: number;
  }) {
    const canvas = useRef<HTMLCanvasElement>(null);
    const isIead = 'angles' in grid;
    const width = rasterSize(isIead ? grid.energies.length : grid.rows.length, box.width);
    const height = rasterSize(isIead ? grid.angles.length : 0, box.height);
    const viewHeight = box.height;
    useEffect(() => {
      const context = canvas.current?.getContext('2d');
      if (!context) return;
      const color = heatColors(min, max);
      if ('angles' in grid) {
        paintIead(context, grid, width, height, color);
      } else {
        context.clearRect(0, 0, width, height);
        const xEdges = rasterEdges(grid.rows.map(row => row[0]), width);
        const scale = height / viewHeight;
        grid.rows.forEach(([,distances,values], row) => {
          distances.forEach((_, index) => {
            const cell = densityCell(distances, index, maxDistance);
            context.fillStyle = heatColorCss(color(values[index]));
            context.fillRect(xEdges[row], cell.y * scale, xEdges[row + 1] - xEdges[row], cell.height * scale);
          });
        });
      }
    }, [grid,width,height,min,max,maxDistance,viewHeight]);
    return <foreignObject {...box} aria-hidden="true"><canvas ref={canvas} width={width} height={height} style={{display:'block',width:'100%',height:'100%',imageRendering:'pixelated'}}/></foreignObject>;
  }

  export function renderIeAdHeatmap(iead: Iead | null, sharedRange: Range | null = null) {
    if (!iead?.values.length || !iead.energies.length || !iead.angles.length) return <><div className="analysis-chart-empty">IEAD 데이터가 없습니다.</div></>;
    const width = 720;
    const height = heatmapHeight;
    const pad = { left: 56, right: 26, top: heatmapTop, bottom: heatmapBottom };
    const cols = iead.energies.length;
    const range = sharedRange || positiveRange(iead.values);
    const min = range?.min ?? 0;
    const max = range?.max ?? 0;
    const plotWidth = width - pad.left - pad.right;
    const color = heatColors(min, max);
    let cells;
    if (iead.values.length > svgCellLimit) {
      cells = <HeatmapRaster grid={iead} box={{x:pad.left,y:pad.top,width:plotWidth,height:heatmapPlotHeight}} min={min} max={max}/>;
    } else {
      const xEdges = cellEdges(iead.energies);
      const yEdges = cellEdges(iead.angles);
      cells = iead.values.map((value, index) => {
        const row = Math.floor(index / cols);
        const col = index % cols;
        return <rect key={index} x={(pad.left + xEdges[col] * plotWidth).toFixed(2)} y={(pad.top + (1 - yEdges[row + 1]) * heatmapPlotHeight).toFixed(2)} width={((xEdges[col + 1] - xEdges[col]) * plotWidth + 0.25).toFixed(2)} height={((yEdges[row + 1] - yEdges[row]) * heatmapPlotHeight + 0.25).toFixed(2)} fill={heatColorCss(color(value))}/>;
      });
    }
    return <><svg className="analysis-heatmap-svg" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Ion Energy Angle Distribution 실제 수치 히트맵">
      {cells}<line x1={pad.left} y1={height - pad.bottom} x2={width - pad.right} y2={height - pad.bottom} className="analysis-axis"></line><line x1={pad.left} y1={pad.top} x2={pad.left} y2={height - pad.bottom} className="analysis-axis"></line>
      <text x={pad.left} y={height - 25} className="analysis-axis-label">{compactNumber(iead.energies[0])}</text><text x={width - pad.right} y={height - 25} textAnchor="end" className="analysis-axis-label">{compactNumber(iead.energies.at(-1))}</text>
      <text x={width / 2} y={height - 5} textAnchor="middle" className="analysis-axis-title">Ion energy (eV)</text><text x="16" y={height / 2} textAnchor="middle" transform={`rotate(-90 16 ${height / 2})`} className="analysis-axis-title">Incident angle (°)</text>
      <text x={pad.left - 9} y={height - pad.bottom + 4} textAnchor="end" className="analysis-axis-label">{compactNumber(iead.angles[0])}</text><text x={pad.left - 9} y={pad.top + 4} textAnchor="end" className="analysis-axis-label">{compactNumber(iead.angles.at(-1))}</text>
    </svg></>;
  }

  export function renderDensityHeatmap(density: Density | null, sharedRange: Range | null = null) {
    if (!density || !density.rows || !density.rows.length) return <><div className="analysis-chart-empty">쉬스 밀도 데이터가 없습니다.</div></>;
    const width = 720;
    const height = heatmapHeight;
    const pad = { left: 64, right: 26, top: heatmapTop, bottom: heatmapBottom };
    const maxDistance = density.rows.reduce((maximum, row) => Math.max(maximum, row[1].at(-1) ?? 0), 0);
    const values = density.rows.flatMap((row) => row[2]);
    const range = sharedRange || positiveRange(values);
    const min = range?.min ?? 0;
    const max = range?.max ?? 0;
    const plotWidth = width - pad.left - pad.right;
    const color = heatColors(min, max);
    let cells;
    if (values.length > svgCellLimit) {
      cells = <HeatmapRaster grid={density} box={{x:pad.left,y:0,width:plotWidth,height}} min={min} max={max} maxDistance={maxDistance || 1}/>;
    } else {
      const xEdges = cellEdges(density.rows.map(row => row[0]));
      cells = density.rows.flatMap(([, distances, values], row) => distances.map((_, index) => {
        const cell = densityCell(distances, index, maxDistance || 1);
        return <rect key={`${row}-${index}`} x={(pad.left + xEdges[row] * plotWidth).toFixed(2)} y={cell.y.toFixed(2)} width={((xEdges[row + 1] - xEdges[row]) * plotWidth + 0.3).toFixed(2)} height={cell.height.toFixed(2)} fill={heatColorCss(color(values[index]))}/>;
      }));
    }
    return <><svg className="analysis-heatmap-svg" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="위상별 쉬스 이온 밀도 실제 수치 히트맵">
      {cells}<line x1={pad.left} y1={height - pad.bottom} x2={width - pad.right} y2={height - pad.bottom} className="analysis-axis"></line><line x1={pad.left} y1={pad.top} x2={pad.left} y2={height - pad.bottom} className="analysis-axis"></line>
      <text x={pad.left} y={height - 25} className="analysis-axis-label">{compactNumber(density.rows[0][0])}</text><text x={width - pad.right} y={height - 25} textAnchor="end" className="analysis-axis-label">{compactNumber(density.rows.at(-1)?.[0])}</text><text x={width / 2} y={height - 5} textAnchor="middle" className="analysis-axis-title">RF phase</text>
      <text x={pad.left - 9} y={height - pad.bottom + 4} textAnchor="end" className="analysis-axis-label">0</text><text x={pad.left - 9} y={pad.top + 4} textAnchor="end" className="analysis-axis-label">{compactNumber(maxDistance)}</text><text x="16" y={height / 2} textAnchor="middle" transform={`rotate(-90 16 ${height / 2})`} className="analysis-axis-title">Distance (cm)</text>
    </svg></>;
  }

  export function renderAnalysisChartContent(run: FullRun, tab: string) {
    const analysis = run.analysis;
    if (tab === 'distribution') {
      if (!analysis.hasDistribution) return <><div className="analysis-no-data"><span className="analysis-no-data-icon" aria-hidden="true">0 W</span><h3>Bias-off Run에는 쉬스 분포 출력이 없습니다</h3><p>엔진 완료 결과는 유효하지만 IED·IAD·IEAD는 Bias Power 200 W 이상 Run에서만 제공됩니다. 상단 Bias를 변경해 실제 분포를 확인하세요.</p></div></>;
      const shape = heatmapSampleShape(analysis.iead);
      return <><div className="analysis-chart-stack"><section className="analysis-visual analysis-visual--wide"><div className="analysis-visual-head"><div><span>IEAD</span><h3>이온 에너지–입사각 분포</h3></div><small>{shape?.join(' × ') ?? 0} actual samples</small></div>{renderIeAdHeatmap(analysis.iead)}<div className="heat-legend"><span>Low</span><i></i><span>High · log color</span></div></section>
        <div className="analysis-chart-pair"><section className="analysis-visual"><div className="analysis-visual-head"><div><span>IED</span><h3>Ion Energy Distribution</h3></div><small>{run.iedDistribution.length} samples</small></div>{analysisLineChart(run.iedDistribution.map((point) => [point.energy, point.intensity]), { xLabel: 'Energy (eV)', yLabel: 'Intensity (a.u.)', ariaLabel: 'IED 실제 수치 선 그래프' })}</section>
        <section className="analysis-visual"><div className="analysis-visual-head"><div><span>IAD</span><h3>Ion Angle Distribution</h3></div><small>{analysis.iad?.length ?? 0} samples</small></div>{analysisLineChart(analysis.iad, { xLabel: 'Angle (°)', yLabel: 'Intensity (a.u.)', ariaLabel: 'IAD 실제 수치 선 그래프' })}</section></div></div></>;
    }
    if (tab === 'waveforms') {
      if (!analysis.hasDistribution) return <><div className="analysis-no-data"><span className="analysis-no-data-icon" aria-hidden="true">0 W</span><h3>Bias-off Run에는 RF 파형 출력이 없습니다</h3><p>Bias Power가 적용된 Run을 선택하면 전류 밀도와 전극 전위를 위상별로 비교할 수 있습니다.</p></div></>;
      return <><div className="analysis-chart-pair"><section className="analysis-visual"><div className="analysis-visual-head"><div><span>CURRENT</span><h3>전류 밀도 파형</h3></div><small>{analysis.current?.points.length ?? 0} actual samples</small></div>{analysisLineChart(analysis.current?.points ?? [], { xLabel: 'RF phase', yLabel: 'Current density (statampere/cm²)', ariaLabel: '위상별 전류 밀도 실제 수치 그래프' })}</section>
        <section className="analysis-visual"><div className="analysis-visual-head"><div><span>POTENTIAL</span><h3>전극 전위 파형</h3></div><small>{analysis.potential?.points.length ?? 0} actual samples</small></div>{analysisLineChart(analysis.potential?.points ?? [], { xLabel: 'RF phase', yLabel: 'Potential (V)', ariaLabel: '위상별 전극 전위 실제 수치 그래프' })}</section></div></>;
    }
    if (tab === 'density') {
      if (!analysis.hasDistribution) return <><div className="analysis-no-data"><span className="analysis-no-data-icon" aria-hidden="true">0 W</span><h3>Bias-off Run에는 위상별 쉬스 밀도 출력이 없습니다</h3><p>Bias-on Run에서 Ar+ 쉬스 밀도의 거리·위상 분포를 확인할 수 있습니다.</p></div></>;
      const shape = heatmapSampleShape(analysis.density);
      return <><section className="analysis-visual analysis-visual--wide"><div className="analysis-visual-head"><div><span>SHEATH DENSITY</span><h3>위상별 Ar+ 이온 밀도</h3></div><small>{shape?.join(' × ') ?? 0} actual samples</small></div>{renderDensityHeatmap(analysis.density)}<div className="heat-legend"><span>Low</span><i></i><span>High · log color</span></div><p className="analysis-footnote">각 위상의 실제 sheath edge 길이가 다르므로, 열별 최대 거리가 달라질 수 있습니다.</p></section></>;
    }
    return <><div className="analysis-chart-pair"><section className="analysis-visual analysis-visual--wide"><div className="analysis-visual-head"><div><span>RESIDUAL</span><h3>반복 계산 잔차 추이</h3></div><small>{analysis.residualTrace.length} actual samples · log scale</small></div>{analysisLineChart(analysis.residualTrace, { xLabel: 'Iteration', yLabel: 'Max residual', logY: true, threshold: 1e-8, ariaLabel: '반복 계산 잔차 실제 수치 그래프' })}</section></div><div className={`analysis-quality-note ${analysis.strictConvergence ? 'is-pass' : 'is-review'}`}><strong>{analysis.strictConvergence ? 'Strict threshold 충족' : '엔진 정상 완료 · strict threshold 별도 확인'}</strong><span>최종 max residual {compactNumber(analysis.finalResidualMax)} · strict 기준 ≤ 1.00e-8</span><p>실행 로그의 정상 완료와 최종 잔차 임계 통과를 같은 의미로 표시하지 않습니다.</p></div></>;
  }
