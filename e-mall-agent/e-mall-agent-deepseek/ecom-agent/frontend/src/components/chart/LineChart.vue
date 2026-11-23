<template>
  <div ref="el" class="chart" :style="{ height }" />
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { CHART_AXIS_COLOR, CHART_COLORS, CHART_TEXT_COLOR, type ChartOption } from './echarts'
import { useChart } from './useChart'

export interface LineSeries {
  name: string
  data: number[]
  color?: string
  area?: boolean
}

const props = defineProps<{
  categories: string[]
  series: LineSeries[]
  height?: string
  valueFormatter?: (value: number) => string
}>()

const height = computed(() => props.height ?? '280px')

const option = computed<ChartOption>(() => ({
  color: [...CHART_COLORS],
  grid: { left: 8, right: 16, top: props.series.length > 1 ? 36 : 16, bottom: 4, containLabel: true },
  tooltip: {
    trigger: 'axis',
    valueFormatter: props.valueFormatter,
    backgroundColor: 'rgba(15, 23, 42, 0.92)',
    borderWidth: 0,
    textStyle: { color: '#e2e8f0', fontSize: 12 },
  },
  legend:
    props.series.length > 1
      ? { top: 0, right: 0, icon: 'circle', itemWidth: 8, itemHeight: 8, textStyle: { color: CHART_TEXT_COLOR, fontSize: 11 } }
      : undefined,
  xAxis: {
    type: 'category',
    boundaryGap: false,
    data: props.categories,
    axisLine: { lineStyle: { color: CHART_AXIS_COLOR } },
    axisTick: { show: false },
    axisLabel: { color: CHART_TEXT_COLOR, fontSize: 11 },
  },
  yAxis: {
    type: 'value',
    axisLine: { show: false },
    axisTick: { show: false },
    splitLine: { lineStyle: { color: CHART_AXIS_COLOR, type: 'dashed' } },
    axisLabel: { color: CHART_TEXT_COLOR, fontSize: 11 },
  },
  series: props.series.map((item, index) => ({
    type: 'line' as const,
    name: item.name,
    data: item.data,
    smooth: true,
    showSymbol: false,
    lineStyle: { width: 2, color: item.color ?? CHART_COLORS[index % CHART_COLORS.length] },
    itemStyle: { color: item.color ?? CHART_COLORS[index % CHART_COLORS.length] },
    areaStyle: item.area
      ? { opacity: 0.08, color: item.color ?? CHART_COLORS[index % CHART_COLORS.length] }
      : undefined,
  })),
}))

const { el } = useChart(() => option.value)
</script>

<style scoped>
.chart {
  width: 100%;
}
</style>
