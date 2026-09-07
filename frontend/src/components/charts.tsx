import type { EChartsOption } from 'echarts';

import { EChart } from './EChart';
import { RATING_COLORS, STATUS_GROUP_COLORS } from '../utils/colors';
import type {
  EscalationTrend,
  HeatmapData,
  NameValue,
  RatingSlice,
  StackData,
} from '../utils/aggregates';

const AXIS_LABEL = '#64748b';
const GRID_LINE = '#e5e9f0';
const ACCENT = '#14418c';

function emptyOption(message: string): EChartsOption {
  return {
    title: {
      text: message,
      left: 'center',
      top: 'middle',
      textStyle: { color: '#94a3b8', fontSize: 13, fontWeight: 'normal' },
    },
  };
}

/**
 * Consistent legend styling for rating legends (High/Medium/Low).
 *
 * Legends are anchored to the top or bottom edge of the chart and the chart
 * grid reserves space for them, so a legend never shares the strip used by
 * x-axis/category labels.
 */
function ratingLegend(position: 'top' | 'bottom' = 'bottom') {
  const anchor =
    position === 'top' ? { top: 0 } : { bottom: 0 };
  return {
    ...anchor,
    left: 'center',
    itemGap: 18,
    itemWidth: 14,
    itemHeight: 10,
    icon: 'roundRect',
    textStyle: { color: AXIS_LABEL, fontSize: 12 },
    inactiveColor: '#cbd5e1',
  };
}

interface BarClickParams {
  name?: string;
  value?: unknown;
}

function projectClickHandler(
  params: unknown,
  onSelect: (name: string) => void,
) {
  const p = params as BarClickParams;
  if (p.name) onSelect(p.name);
}

/* ------------------------------------------------------------------ */
/* Rating donut (also used by the project dashboard)                   */
/* ------------------------------------------------------------------ */

export function DonutChart({ data }: { data: RatingSlice[] }) {
  if (data.length === 0) {
    return <EChart option={emptyOption('No risks yet')} height={280} />;
  }
  const total = data.reduce((sum, d) => sum + d.value, 0);
  const option: EChartsOption = {
    tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
    legend: ratingLegend('bottom'),
    series: [
      {
        type: 'pie',
        radius: ['52%', '76%'],
        center: ['50%', '45%'],
        data: data.map((d) => ({
          name: d.name,
          value: d.value,
          itemStyle: { color: RATING_COLORS[d.name] },
        })),
        label: { show: false },
        emphasis: { label: { show: true, fontWeight: 'bold' } },
      },
    ],
    title: {
      text: String(total),
      subtext: 'total risks',
      left: 'center',
      top: '36%',
      textStyle: { fontSize: 26, fontWeight: 700, color: '#1e293b' },
      subtextStyle: { fontSize: 11, color: AXIS_LABEL },
    },
  };
  return <EChart option={option} height={280} />;
}

/* ------------------------------------------------------------------ */
/* Status-group donut (portfolio Risk Overview)                        */
/* ------------------------------------------------------------------ */

export function StatusDonutChart({ data }: { data: NameValue[] }) {
  const total = data.reduce((sum, d) => sum + d.value, 0);
  if (total === 0) {
    return <EChart option={emptyOption('No risks yet')} height={260} />;
  }
  const option: EChartsOption = {
    tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
    legend: ratingLegend('bottom'),
    series: [
      {
        type: 'pie',
        radius: ['52%', '76%'],
        center: ['50%', '45%'],
        data: data.map((d) => ({
          name: d.name,
          value: d.value,
          itemStyle: { color: STATUS_GROUP_COLORS[d.name] ?? '#94a3b8' },
        })),
        label: { show: false },
        emphasis: { label: { show: true, fontWeight: 'bold' } },
      },
    ],
    title: {
      text: String(total),
      subtext: 'total risks',
      left: 'center',
      top: '36%',
      textStyle: { fontSize: 26, fontWeight: 700, color: '#1e293b' },
      subtextStyle: { fontSize: 11, color: AXIS_LABEL },
    },
  };
  return <EChart option={option} height={260} />;
}

/* ------------------------------------------------------------------ */
/* Escalated vs non-escalated donut                                    */
/* ------------------------------------------------------------------ */

export function EscalatedDonutChart({ data }: { data: NameValue[] }) {
  const colors: Record<string, string> = {
    Escalated: '#ee1f2f',
    'Not escalated': '#e2e8f0',
  };
  const escalated = data.find((d) => d.name === 'Escalated')?.value ?? 0;
  const option: EChartsOption = {
    tooltip: { trigger: 'item', formatter: '{b}: {c} ({d}%)' },
    legend: ratingLegend('bottom'),
    series: [
      {
        type: 'pie',
        radius: ['55%', '78%'],
        center: ['50%', '45%'],
        data: data.map((d) => ({
          name: d.name,
          value: d.value,
          itemStyle: { color: colors[d.name] ?? '#94a3b8' },
        })),
        label: { show: false },
        emphasis: { label: { show: true, fontWeight: 'bold' } },
      },
    ],
    title: {
      text: String(escalated),
      subtext: 'escalated',
      left: 'center',
      top: '36%',
      textStyle: { fontSize: 26, fontWeight: 700, color: '#ee1f2f' },
      subtextStyle: { fontSize: 11, color: AXIS_LABEL },
    },
  };
  return <EChart option={option} height={260} />;
}

/* ------------------------------------------------------------------ */
/* Horizontal bar: risk distribution by category                       */
/* ------------------------------------------------------------------ */

export function CategoryBarChart({ data }: { data: NameValue[] }) {
  if (data.length === 0) {
    return <EChart option={emptyOption('No categories yet')} height={260} />;
  }
  // Largest at the top.
  const rows = [...data].reverse();
  const option: EChartsOption = {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: '{b}: {c} risks',
    },
    grid: { left: 8, right: 32, top: 8, bottom: 8, containLabel: true },
    xAxis: {
      type: 'value',
      minInterval: 1,
      axisLabel: { color: AXIS_LABEL },
      splitLine: { lineStyle: { color: GRID_LINE } },
    },
    yAxis: {
      type: 'category',
      data: rows.map((d) => d.name),
      axisLabel: { color: AXIS_LABEL },
      axisLine: { lineStyle: { color: GRID_LINE } },
    },
    series: [
      {
        type: 'bar',
        barMaxWidth: 20,
        data: rows.map((d) => ({
          value: d.value,
          itemStyle: {
            color: d.name === 'Other' ? '#cbd5e1' : ACCENT,
            borderRadius: [0, 4, 4, 0],
          },
        })),
        label: { show: true, position: 'right', color: AXIS_LABEL },
      },
    ],
  };
  const height = Math.max(240, data.length * 34 + 30);
  return <EChart option={option} height={height} />;
}

/* ------------------------------------------------------------------ */
/* Horizontal stacked bar: risk by project (top N)                     */
/* ------------------------------------------------------------------ */

export function ProjectStackedBarChart({
  data,
  onSelect,
}: {
  data: StackData;
  onSelect?: (projectCode: string) => void;
}) {
  if (data.categories.length === 0) {
    return <EChart option={emptyOption('No risks yet')} height={300} />;
  }
  const rows = [...data.categories].reverse();
  const series = data.series.map((s) => ({
    name: s.name,
    type: 'bar',
    stack: 'total',
    data: [...s.data].reverse(),
    itemStyle: { color: RATING_COLORS[s.name] },
  }));

  const option: EChartsOption = {
    tooltip: {
      trigger: 'axis',
      axisPointer: { type: 'shadow' },
      formatter: (params: unknown) => {
        const items = params as { name: string; seriesName: string; value: number }[];
        if (!items || items.length === 0) return '';
        const total = items.reduce((sum, i) => sum + i.value, 0);
        const breakdown = items
          .map((i) => `${i.seriesName}: ${i.value}`)
          .join('<br/>');
        return `<b>${items[0].name}</b><br/>Total risks: ${total}<br/>${breakdown}`;
      },
    },
    legend: ratingLegend('top'),
    grid: { left: 8, right: 32, top: 40, bottom: 8, containLabel: true },
    xAxis: {
      type: 'value',
      minInterval: 1,
      axisLabel: { color: AXIS_LABEL },
      splitLine: { lineStyle: { color: GRID_LINE } },
    },
    yAxis: {
      type: 'category',
      data: rows,
      axisLabel: { color: AXIS_LABEL, fontSize: 11 },
      axisLine: { lineStyle: { color: GRID_LINE } },
    },
    dataZoom:
      data.categories.length > 12
        ? [{ type: 'inside', yAxisIndex: 0 }]
        : undefined,
    series: series as EChartsOption['series'],
  };
  const height =
    data.categories.length > 12
      ? 520
      : Math.max(300, data.categories.length * 30 + 90);
  return (
    <EChart
      option={option}
      height={height}
      onClick={onSelect ? (p) => projectClickHandler(p, onSelect) : undefined}
    />
  );
}

/* ------------------------------------------------------------------ */
/* Heatmap: project × category (top projects, grouped categories)      */
/* ------------------------------------------------------------------ */

export function HeatmapChart({
  data,
  onSelect,
}: {
  data: HeatmapData;
  onSelect?: (projectCode: string) => void;
}) {
  if (data.data.length === 0) {
    return <EChart option={emptyOption('No risk data yet')} height={300} />;
  }
  const max = Math.max(1, ...data.data.map((d) => d[2]));

  const option: EChartsOption = {
    tooltip: {
      position: 'top',
      formatter: (params: unknown) => {
        const p = params as { value: [number, number, number] };
        const cat = data.categories[p.value[0]] ?? '?';
        const proj = data.projects[p.value[1]] ?? '?';
        return `<b>${proj}</b><br/>${cat}: ${p.value[2]} risk${p.value[2] === 1 ? '' : 's'}`;
      },
    },
    grid: { left: 8, right: 24, top: 16, bottom: 92, containLabel: true },
    xAxis: {
      type: 'category',
      data: data.categories,
      axisLabel: {
        color: AXIS_LABEL,
        interval: 0,
        rotate: data.categories.length > 6 ? 32 : 0,
        fontSize: 11,
        // Truncate long category names so rotated labels stay compact and can
        // never reach the colour scale below them.
        formatter: (value: string) =>
          value.length > 16 ? `${value.slice(0, 15)}…` : value,
      },
      axisLine: { lineStyle: { color: GRID_LINE } },
    },
    yAxis: {
      type: 'category',
      data: data.projects,
      axisLabel: { color: AXIS_LABEL, fontSize: 11 },
      axisLine: { lineStyle: { color: GRID_LINE } },
    },
    dataZoom:
      data.projects.length > 12
        ? [{ type: 'inside', yAxisIndex: 0 }]
        : undefined,
    visualMap: {
      min: 0,
      max,
      calculable: true,
      orient: 'horizontal',
      left: 'center',
      bottom: 0,
      itemWidth: 140,
      itemHeight: 12,
      textGap: 10,
      inRange: { color: ['#e8eef9', '#14418c', '#ee1f2f'] },
      textStyle: { color: AXIS_LABEL, fontSize: 11 },
    },
    series: [
      {
        type: 'heatmap',
        data: data.data,
        label: { show: false },
        emphasis: {
          itemStyle: { borderColor: '#1e293b', borderWidth: 1 },
        },
        itemStyle: { borderColor: '#ffffff', borderWidth: 3, borderRadius: 3 },
      },
    ],
  };
  const height =
    data.projects.length > 12
      ? 520
      : Math.max(300, data.projects.length * 28 + 130);
  return (
    <EChart
      option={option}
      height={height}
      onClick={onSelect ? (p) => projectClickHandler(p, onSelect) : undefined}
    />
  );
}

/* ------------------------------------------------------------------ */
/* Escalation trend line                                               */
/* ------------------------------------------------------------------ */

export function EscalationTrendChart({ data }: { data: EscalationTrend }) {
  if (data.months.length === 0) {
    return <EChart option={emptyOption('No escalations yet')} height={260} />;
  }
  const option: EChartsOption = {
    tooltip: {
      trigger: 'axis',
      formatter: (params: unknown) => {
        const items = params as { axisValue: string; value: number }[];
        const first = items[0];
        return `${first.axisValue}: ${first.value} escalated`;
      },
    },
    grid: { left: 40, right: 20, top: 20, bottom: 34, containLabel: true },
    xAxis: {
      type: 'category',
      boundaryGap: false,
      data: data.months,
      axisLabel: { color: AXIS_LABEL },
      axisLine: { lineStyle: { color: GRID_LINE } },
    },
    yAxis: {
      type: 'value',
      minInterval: 1,
      axisLabel: { color: AXIS_LABEL },
      splitLine: { lineStyle: { color: GRID_LINE } },
    },
    series: [
      {
        type: 'line',
        data: data.values,
        smooth: true,
        symbol: 'circle',
        symbolSize: 8,
        itemStyle: { color: '#ee1f2f', borderColor: '#ffffff', borderWidth: 2 },
        lineStyle: { color: '#ee1f2f', width: 2.5 },
        areaStyle: { color: 'rgba(238,31,47,0.10)' },
      },
    ],
  };
  return <EChart option={option} height={260} />;
}

/* ------------------------------------------------------------------ */
/* Project dashboard charts (kept for the project view)                */
/* ------------------------------------------------------------------ */

export function StackedBarChart({ data }: { data: StackData }) {
  if (data.categories.length === 0) {
    return <EChart option={emptyOption('No risks yet')} height={300} />;
  }
  const hasMany = data.categories.length >= 5;
  const option: EChartsOption = {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    // Legend above the plot; x-axis/category labels get the whole bottom strip
    // (grid.bottom) so they can never collide with the legend.
    legend: ratingLegend('top'),
    grid: {
      left: 44,
      right: 16,
      top: 40,
      bottom: hasMany ? 62 : 48,
    },
    xAxis: {
      type: 'category',
      data: data.categories,
      axisLabel: {
        color: AXIS_LABEL,
        interval: 0,
        // Long status names (e.g. "Suggested", "In Progress") are rotated only
        // when there are enough categories to need it; the extra bottom margin
        // keeps the rotated labels clear of the chart edge.
        rotate: hasMany ? 30 : 0,
      },
      axisLine: { lineStyle: { color: GRID_LINE } },
    },
    yAxis: {
      type: 'value',
      minInterval: 1,
      axisLabel: { color: AXIS_LABEL },
      splitLine: { lineStyle: { color: GRID_LINE } },
    },
    series: data.series.map((s) => ({
      name: s.name,
      type: 'bar',
      stack: 'total',
      data: s.data,
      itemStyle: { color: RATING_COLORS[s.name] },
    })),
  };
  return <EChart option={option} height={300} />;
}

export function TreemapChart({ data }: { data: NameValue[] }) {
  if (data.length === 0) {
    return <EChart option={emptyOption('No categories yet')} height={300} />;
  }
  const option: EChartsOption = {
    tooltip: { formatter: '{b}: {c}' },
    series: [
      {
        type: 'treemap',
        roam: false,
        nodeClick: false,
        breadcrumb: { show: false },
        data,
        label: { show: true, color: '#ffffff', fontSize: 12 },
        itemStyle: { borderColor: '#ffffff', borderWidth: 2, gapWidth: 2 },
        levels: [
          {
            color: ['#0e3168', '#14418c', '#4a76b8', '#8aa8d6'],
          },
        ],
      },
    ],
  };
  return <EChart option={option} height={300} />;
}
