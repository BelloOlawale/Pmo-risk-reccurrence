import type { EChartsOption } from 'echarts';

import { EChart } from './EChart';
import { RATING_COLORS } from '../utils/colors';
import type {
  EscalationTrend,
  HeatmapData,
  NameValue,
  RatingSlice,
  StackData,
} from '../utils/aggregates';

const AXIS_LABEL = '#8fa3bf';
const GRID_LINE = '#22314a';

function emptyOption(message: string): EChartsOption {
  return {
    title: {
      text: message,
      left: 'center',
      top: 'middle',
      textStyle: { color: '#5f7290', fontSize: 13, fontWeight: 'normal' },
    },
  };
}

export function DonutChart({ data }: { data: RatingSlice[] }) {
  if (data.length === 0) {
    return <EChart option={emptyOption('No risks yet')} height={280} />;
  }
  const option: EChartsOption = {
    tooltip: { trigger: 'item' },
    legend: { bottom: 0, textStyle: { color: AXIS_LABEL } },
    series: [
      {
        type: 'pie',
        radius: ['45%', '72%'],
        center: ['50%', '45%'],
        data: data.map((d) => ({ ...d, itemStyle: { color: RATING_COLORS[d.name] } })),
        label: { color: AXIS_LABEL, formatter: '{b}: {c}' },
      },
    ],
  };
  return <EChart option={option} height={280} />;
}

export function StackedBarChart({ data }: { data: StackData }) {
  if (data.categories.length === 0) {
    return <EChart option={emptyOption('No risks yet')} height={300} />;
  }
  const option: EChartsOption = {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: { bottom: 0, textStyle: { color: AXIS_LABEL } },
    grid: { left: 40, right: 16, top: 20, bottom: 44 },
    xAxis: {
      type: 'category',
      data: data.categories,
      axisLabel: { color: AXIS_LABEL, interval: 0, rotate: 30 },
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
        label: { show: true, color: '#e6edf7', fontSize: 12 },
        itemStyle: { borderColor: '#0b1220', borderWidth: 2, gapWidth: 2 },
        levels: [
          {
            color: ['#312e81', '#6366f1', '#818cf8', '#a5b4fc'],
          },
        ],
      },
    ],
  };
  return <EChart option={option} height={300} />;
}

export function HeatmapChart({ data }: { data: HeatmapData }) {
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
        return `${proj} × ${cat}: <b>${p.value[2]}</b> risk(s)`;
      },
    },
    grid: { left: 130, right: 20, top: 20, bottom: 70 },
    xAxis: {
      type: 'category',
      data: data.categories,
      axisLabel: { color: AXIS_LABEL, interval: 0, rotate: 40 },
      splitArea: { show: true, areaStyle: { color: ['rgba(255,255,255,0.02)'] } },
      axisLine: { lineStyle: { color: GRID_LINE } },
    },
    yAxis: {
      type: 'category',
      data: data.projects,
      axisLabel: { color: AXIS_LABEL },
      splitArea: { show: true, areaStyle: { color: ['rgba(255,255,255,0.02)'] } },
      axisLine: { lineStyle: { color: GRID_LINE } },
    },
    visualMap: {
      min: 0,
      max,
      calculable: true,
      orient: 'horizontal',
      left: 'center',
      bottom: 0,
      inRange: { color: ['#111a2c', '#6366f1', '#ef4444'] },
      textStyle: { color: AXIS_LABEL },
    },
    series: [
      {
        type: 'heatmap',
        data: data.data,
        label: { show: true, color: '#e6edf7' },
        itemStyle: { borderColor: '#0b1220', borderWidth: 2 },
      },
    ],
  };
  return <EChart option={option} height={300} />;
}

export function ProjectBarChart({ data }: { data: StackData }) {
  if (data.categories.length === 0) {
    return <EChart option={emptyOption('No risks yet')} height={300} />;
  }
  const option: EChartsOption = {
    tooltip: { trigger: 'axis', axisPointer: { type: 'shadow' } },
    legend: { bottom: 0, textStyle: { color: AXIS_LABEL } },
    grid: { left: 40, right: 16, top: 20, bottom: 44 },
    xAxis: {
      type: 'category',
      data: data.categories,
      axisLabel: { color: AXIS_LABEL, interval: 0, rotate: 30 },
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

export function EscalationTrendChart({ data }: { data: EscalationTrend }) {
  if (data.months.length === 0) {
    return <EChart option={emptyOption('No escalations yet')} height={300} />;
  }
  const option: EChartsOption = {
    tooltip: { trigger: 'axis' },
    grid: { left: 40, right: 20, top: 20, bottom: 40 },
    xAxis: {
      type: 'category',
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
        symbolSize: 8,
        itemStyle: { color: '#ef4444' },
        lineStyle: { color: '#ef4444', width: 2 },
        areaStyle: { color: 'rgba(239,68,68,0.15)' },
      },
    ],
  };
  return <EChart option={option} height={300} />;
}
