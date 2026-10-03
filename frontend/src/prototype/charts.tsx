import {Fragment, type CSSProperties} from 'react';
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
    const xs = pairs.map((point) => point.x);
    const rawYs = pairs.map((point) => point.y);
    const transformedYs = options.logY ? rawYs.map((value) => Math.log10(value)) : rawYs;
    const minX = Math.min(...xs);
    let maxX = Math.max(...xs);
    let minY = Math.min(...transformedYs);
    let maxY = Math.max(...transformedYs);
    if (!options.logY && minY > 0) minY = 0;
    if (minX === maxX) maxX += 1;
    if (minY === maxY) maxY += 1;
    const plotWidth = width - pad.left - pad.right;
    const plotHeight = height - pad.top - pad.bottom;
    const xy = pairs.map((point, index) => ({
      x: pad.left + ((point.x - minX) / (maxX - minX)) * plotWidth,
      y: pad.top + (1 - (transformedYs[index] - minY) / (maxY - minY)) * plotHeight,
    }));
    const path = xy.map((point, index) => `${index ? 'L' : 'M'}${point.x.toFixed(1)} ${point.y.toFixed(1)}`).join(' ');
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

  export function blueHeatColor(value: number, min: number, max: number, useLog = true) {
    if (!Number.isFinite(value) || value <= 0) return '#f2f5fb';
    const start = useLog ? Math.log10(Math.max(min, Number.MIN_VALUE)) : min;
    const end = useLog ? Math.log10(Math.max(max, Number.MIN_VALUE)) : max;
    const current = useLog ? Math.log10(value) : value;
    const ratio = Math.max(0, Math.min(1, (current - start) / Math.max(end - start, Number.EPSILON)));
    const eased = Math.pow(ratio, 0.72);
    const rgb = [
      Math.round(239 + (34 - 239) * eased),
      Math.round(244 + (76 - 244) * eased),
      Math.round(255 + (170 - 255) * eased),
    ];
    return `rgb(${rgb.join(',')})`;
  }

  export function renderIeAdHeatmap(iead: Iead | null, sharedRange: Range | null = null) {
    if (!iead || !iead.values || !iead.values.length) return <><div className="analysis-chart-empty">IEAD 데이터가 없습니다.</div></>;
    const width = 720;
    const height = 360;
    const pad = { left: 56, right: 26, top: 20, bottom: 48 };
    const cols = iead.energies.length;
    const rows = iead.angles.length;
    const range = sharedRange || positiveRange(iead.values);
    const min = range?.min ?? 0;
    const max = range?.max ?? 0;
    const cellWidth = (width - pad.left - pad.right) / cols;
    const cellHeight = (height - pad.top - pad.bottom) / rows;
    const rects = iead.values.map((value, index) => {
      const row = Math.floor(index / cols);
      const col = index % cols;
      return <Fragment key={index}><rect x={(pad.left + col * cellWidth).toFixed(2)} y={(pad.top + (rows - row - 1) * cellHeight).toFixed(2)} width={(cellWidth + 0.25).toFixed(2)} height={(cellHeight + 0.25).toFixed(2)} fill={blueHeatColor(value, min, max)}></rect></Fragment>;
    });
    return <><svg className="analysis-heatmap-svg" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Ion Energy Angle Distribution 실제 수치 히트맵">
      {rects}<line x1={pad.left} y1={height - pad.bottom} x2={width - pad.right} y2={height - pad.bottom} className="analysis-axis"></line><line x1={pad.left} y1={pad.top} x2={pad.left} y2={height - pad.bottom} className="analysis-axis"></line>
      <text x={pad.left} y={height - 25} className="analysis-axis-label">{compactNumber(iead.energies[0])}</text><text x={width - pad.right} y={height - 25} textAnchor="end" className="analysis-axis-label">{compactNumber(iead.energies.at(-1))}</text>
      <text x={width / 2} y={height - 5} textAnchor="middle" className="analysis-axis-title">Ion energy (eV)</text><text x="16" y={height / 2} textAnchor="middle" transform={`rotate(-90 16 ${height / 2})`} className="analysis-axis-title">Incident angle (°)</text>
      <text x={pad.left - 9} y={height - pad.bottom + 4} textAnchor="end" className="analysis-axis-label">{compactNumber(iead.angles[0])}</text><text x={pad.left - 9} y={pad.top + 4} textAnchor="end" className="analysis-axis-label">{compactNumber(iead.angles.at(-1))}</text>
    </svg></>;
  }

  export function renderDensityHeatmap(density: Density | null, sharedRange: Range | null = null) {
    if (!density || !density.rows || !density.rows.length) return <><div className="analysis-chart-empty">쉬스 밀도 데이터가 없습니다.</div></>;
    const width = 720;
    const height = 360;
    const pad = { left: 64, right: 26, top: 20, bottom: 48 };
    const maxDistance = Math.max(...density.rows.flatMap((row) => row[1]));
    const values = density.rows.flatMap((row) => row[2]);
    const range = sharedRange || positiveRange(values);
    const min = range?.min ?? 0;
    const max = range?.max ?? 0;
    const cellWidth = (width - pad.left - pad.right) / density.rows.length;
    const rects = density.rows.flatMap((row, rowIndex) => row[1].map((distance, distanceIndex) => {
      const nextDistance = row[1][Math.min(distanceIndex + 1, row[1].length - 1)];
      const priorDistance = row[1][Math.max(distanceIndex - 1, 0)];
      const cellDistance = distanceIndex === row[1].length - 1 ? distance - priorDistance : nextDistance - distance;
      const y = pad.top + (1 - distance / maxDistance) * (height - pad.top - pad.bottom);
      const cellHeight = Math.max(1, cellDistance / maxDistance * (height - pad.top - pad.bottom));
      return <Fragment key={`${rowIndex}-${distanceIndex}`}><rect x={(pad.left + rowIndex * cellWidth).toFixed(2)} y={(y - cellHeight / 2).toFixed(2)} width={(cellWidth + 0.3).toFixed(2)} height={(cellHeight + 0.5).toFixed(2)} fill={blueHeatColor(row[2][distanceIndex], min, max)}></rect></Fragment>;
    }));
    return <><svg className="analysis-heatmap-svg" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="위상별 쉬스 이온 밀도 실제 수치 히트맵">
      {rects}<line x1={pad.left} y1={height - pad.bottom} x2={width - pad.right} y2={height - pad.bottom} className="analysis-axis"></line><line x1={pad.left} y1={pad.top} x2={pad.left} y2={height - pad.bottom} className="analysis-axis"></line>
      <text x={pad.left} y={height - 25} className="analysis-axis-label">0</text><text x={width - pad.right} y={height - 25} textAnchor="end" className="analysis-axis-label">1</text><text x={width / 2} y={height - 5} textAnchor="middle" className="analysis-axis-title">RF phase</text>
      <text x={pad.left - 9} y={height - pad.bottom + 4} textAnchor="end" className="analysis-axis-label">0</text><text x={pad.left - 9} y={pad.top + 4} textAnchor="end" className="analysis-axis-label">{compactNumber(maxDistance)}</text><text x="16" y={height / 2} textAnchor="middle" transform={`rotate(-90 16 ${height / 2})`} className="analysis-axis-title">Distance (m)</text>
    </svg></>;
  }

  export function renderAnalysisChartContent(run: FullRun, tab: string) {
    const analysis = run.analysis;
    if (tab === 'distribution') {
      if (!analysis.hasDistribution) return <><div className="analysis-no-data"><span className="analysis-no-data-icon" aria-hidden="true">0 W</span><h3>Bias-off Run에는 쉬스 분포 출력이 없습니다</h3><p>엔진 완료 결과는 유효하지만 IED·IAD·IEAD는 Bias Power 200 W 이상 Run에서만 제공됩니다. 상단 Bias를 변경해 실제 분포를 확인하세요.</p></div></>;
      return <><div className="analysis-chart-stack"><section className="analysis-visual analysis-visual--wide"><div className="analysis-visual-head"><div><span>IEAD</span><h3>이온 에너지–입사각 분포</h3></div><small>31 × 61 actual samples</small></div>{renderIeAdHeatmap(analysis.iead)}<div className="heat-legend"><span>Low</span><i></i><span>High · log color</span></div></section>
        <div className="analysis-chart-pair"><section className="analysis-visual"><div className="analysis-visual-head"><div><span>IED</span><h3>Ion Energy Distribution</h3></div><small>{run.iedDistribution.length} samples</small></div>{analysisLineChart(run.iedDistribution.map((point) => [point.energy, point.intensity]), { xLabel: 'Energy (eV)', yLabel: 'Intensity (a.u.)', ariaLabel: 'IED 실제 수치 선 그래프' })}</section>
        <section className="analysis-visual"><div className="analysis-visual-head"><div><span>IAD</span><h3>Ion Angle Distribution</h3></div><small>{analysis.iad?.length ?? 0} samples</small></div>{analysisLineChart(analysis.iad, { xLabel: 'Angle (°)', yLabel: 'Intensity (a.u.)', ariaLabel: 'IAD 실제 수치 선 그래프' })}</section></div></div></>;
    }
    if (tab === 'waveforms') {
      if (!analysis.hasDistribution) return <><div className="analysis-no-data"><span className="analysis-no-data-icon" aria-hidden="true">0 W</span><h3>Bias-off Run에는 RF 파형 출력이 없습니다</h3><p>Bias Power가 적용된 Run을 선택하면 전류 밀도와 전극 전위를 위상별로 비교할 수 있습니다.</p></div></>;
      return <><div className="analysis-chart-pair"><section className="analysis-visual"><div className="analysis-visual-head"><div><span>CURRENT</span><h3>전류 밀도 파형</h3></div><small>{analysis.current?.points.length ?? 0} actual samples</small></div>{analysisLineChart(analysis.current?.points ?? [], { xLabel: 'RF phase', yLabel: 'Current density (A/m²)', ariaLabel: '위상별 전류 밀도 실제 수치 그래프' })}</section>
        <section className="analysis-visual"><div className="analysis-visual-head"><div><span>POTENTIAL</span><h3>전극 전위 파형</h3></div><small>{analysis.potential?.points.length ?? 0} actual samples</small></div>{analysisLineChart(analysis.potential?.points ?? [], { xLabel: 'RF phase', yLabel: 'Potential (V)', ariaLabel: '위상별 전극 전위 실제 수치 그래프' })}</section></div></>;
    }
    if (tab === 'density') {
      if (!analysis.hasDistribution) return <><div className="analysis-no-data"><span className="analysis-no-data-icon" aria-hidden="true">0 W</span><h3>Bias-off Run에는 위상별 쉬스 밀도 출력이 없습니다</h3><p>Bias-on Run에서 Ar+ 쉬스 밀도의 거리·위상 분포를 확인할 수 있습니다.</p></div></>;
      return <><section className="analysis-visual analysis-visual--wide"><div className="analysis-visual-head"><div><span>SHEATH DENSITY</span><h3>위상별 Ar+ 이온 밀도</h3></div><small>41 × 31 actual samples</small></div>{renderDensityHeatmap(analysis.density)}<div className="heat-legend"><span>Low</span><i></i><span>High · log color</span></div><p className="analysis-footnote">각 위상의 실제 sheath edge 길이가 다르므로, 열별 최대 거리가 달라질 수 있습니다.</p></section></>;
    }
    return <><div className="analysis-chart-pair"><section className="analysis-visual analysis-visual--wide"><div className="analysis-visual-head"><div><span>RESIDUAL</span><h3>반복 계산 잔차 추이</h3></div><small>{analysis.residualTrace.length} actual samples · log scale</small></div>{analysisLineChart(analysis.residualTrace, { xLabel: 'Iteration', yLabel: 'Max residual', logY: true, threshold: 1e-8, ariaLabel: '반복 계산 잔차 실제 수치 그래프' })}</section></div><div className={`analysis-quality-note ${analysis.strictConvergence ? 'is-pass' : 'is-review'}`}><strong>{analysis.strictConvergence ? 'Strict threshold 충족' : '엔진 정상 완료 · strict threshold 별도 확인'}</strong><span>최종 max residual {compactNumber(analysis.finalResidualMax)} · strict 기준 ≤ 1.00e-8</span><p>실행 로그의 정상 완료와 최종 잔차 임계 통과를 같은 의미로 표시하지 않습니다.</p></div></>;
  }
