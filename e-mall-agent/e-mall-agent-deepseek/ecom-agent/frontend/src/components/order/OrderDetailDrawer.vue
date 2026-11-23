<template>
  <el-drawer :model-value="visible" title="订单详情" size="520px" @update:model-value="onVisibleChange">
    <DataState
      :loading="loading"
      :error="error"
      :empty="!loading && !order && !error"
      empty-text="暂未选择订单"
      @retry="load"
    >
      <div v-if="order" class="order-detail">
        <div class="order-detail__head">
          <span class="order-detail__no mono">{{ order.orderNo }}</span>
          <el-tag size="small" :type="statusMeta.tone" effect="plain">{{ statusMeta.label }}</el-tag>
        </div>

        <el-descriptions :column="2" border size="small" class="mt-12">
          <el-descriptions-item label="下单时间">{{ formatDateTime(order.createdAt) }}</el-descriptions-item>
          <el-descriptions-item label="收货人">{{ order.receiverName || '—' }}</el-descriptions-item>
          <el-descriptions-item label="联系电话">{{ order.receiverPhone || '—' }}</el-descriptions-item>
          <el-descriptions-item label="商品件数">{{ itemCount }}</el-descriptions-item>
          <el-descriptions-item label="订单金额">{{ formatMoney(order.totalAmount) }}</el-descriptions-item>
          <el-descriptions-item label="实付金额">
            <span class="text-strong">{{ formatMoney(order.payAmount) }}</span>
          </el-descriptions-item>
        </el-descriptions>

        <h4 class="order-detail__section">商品明细</h4>
        <el-table :data="order.items" size="small" border>
          <el-table-column prop="title" label="商品" min-width="180" />
          <el-table-column label="单价" width="100" align="right">
            <template #default="{ row }">{{ formatMoney(row.price) }}</template>
          </el-table-column>
          <el-table-column prop="quantity" label="数量" width="70" align="right" />
        </el-table>

        <h4 class="order-detail__section">物流轨迹</h4>
        <LogisticsTimeline :logistics="logistics" />
      </div>
    </DataState>
  </el-drawer>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { getLogistics, getOrder } from '@/api/order'
import type { LogisticsVO, OrderVO } from '@/types'
import { errorMessage } from '@/utils/guard'
import { ORDER_STATUS_META, formatDateTime, formatMoney, metaOf } from '@/utils/format'
import DataState from '@/components/common/DataState.vue'
import LogisticsTimeline from './LogisticsTimeline.vue'

const props = defineProps<{ visible: boolean; orderNo: string }>()
const emit = defineEmits<{ 'update:visible': [visible: boolean] }>()

const order = ref<OrderVO | null>(null)
const logistics = ref<LogisticsVO | null>(null)
const loading = ref(false)
const error = ref('')

const statusMeta = computed(() => metaOf(ORDER_STATUS_META, order.value?.status))
const itemCount = computed(() =>
  (order.value?.items ?? []).reduce((sum, item) => sum + (item.quantity || 0), 0),
)

async function load(): Promise<void> {
  if (!props.orderNo) return
  loading.value = true
  error.value = ''
  try {
    const [orderData, logisticsData] = await Promise.all([
      getOrder(props.orderNo),
      // 物流可能尚未生成，失败不影响订单详情
      getLogistics(props.orderNo).catch((err: unknown) => {
        console.warn('[order] logistics unavailable:', err)
        return null
      }),
    ])
    order.value = orderData
    logistics.value = logisticsData
  } catch (err) {
    error.value = errorMessage(err, '订单详情加载失败')
    order.value = null
    logistics.value = null
  } finally {
    loading.value = false
  }
}

function onVisibleChange(value: boolean): void {
  emit('update:visible', value)
}

watch(
  () => [props.visible, props.orderNo] as const,
  ([visible, orderNo]) => {
    if (visible && orderNo) void load()
  },
  { immediate: true },
)
</script>

<style scoped lang="scss">
.order-detail {
  &__head {
    display: flex;
    align-items: center;
    gap: 10px;
  }

  &__no {
    font-size: 14px;
    font-weight: 600;
  }

  &__section {
    margin: 18px 0 8px;
    font-size: 14px;
    font-weight: 600;
  }
}
</style>
