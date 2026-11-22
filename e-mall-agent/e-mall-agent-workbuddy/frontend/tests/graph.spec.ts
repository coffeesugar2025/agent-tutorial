import { mount } from '@vue/test-utils'
import { describe, expect, it } from 'vitest'
import GraphFlow from '../src/components/GraphFlow.vue'
import type { GraphDescription } from '../src/types'

const graph: GraphDescription = {
  title: '测试工作流',
  nodes: [
    { id: 'start', label: '开始校验', kind: 'process' },
    { id: 'decision', label: '库存判断', kind: 'decision' },
    { id: 'end', label: '履约完成', kind: 'end' },
  ],
  edges: [
    { source: 'start', target: 'decision', label: '通过' },
    { source: 'decision', target: 'end' },
  ],
}

describe('GraphFlow', () => {
  it('renders the title and all node labels in an SVG', () => {
    const wrapper = mount(GraphFlow, { props: { graph } })

    expect(wrapper.text()).toContain('测试工作流')
    expect(wrapper.text()).toContain('开始校验')
    expect(wrapper.text()).toContain('库存判断')
    expect(wrapper.text()).toContain('履约完成')
    expect(wrapper.find('svg').exists()).toBe(true)
    expect(wrapper.findAll('svg text').length).toBeGreaterThanOrEqual(3)
  })

  it('renders edge labels when provided', () => {
    const wrapper = mount(GraphFlow, { props: { graph } })
    expect(wrapper.text()).toContain('通过')
  })
})
