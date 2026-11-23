import * as echarts from 'echarts/core'
import { BarChart, LineChart, PieChart } from 'echarts/charts'
import { GridComponent, LegendComponent, TitleComponent, TooltipComponent } from 'echarts/components'
import { CanvasRenderer } from 'echarts/renderers'

echarts.use([
  BarChart,
  LineChart,
  PieChart,
  GridComponent,
  LegendComponent,
  TitleComponent,
  TooltipComponent,
  CanvasRenderer,
])

export { echarts }

export type ChartInstance = ReturnType<typeof echarts.init>
export type ChartOption = Parameters<ChartInstance['setOption']>[0]

export const CHART_COLORS = ['#2f6bff', '#16a34a', '#f59e0b', '#dc2626', '#7c3aed', '#0891b2'] as const

export const CHART_TEXT_COLOR = '#6b7280'
export const CHART_AXIS_COLOR = '#e5e7eb'
