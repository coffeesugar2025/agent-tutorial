<template>
  <div class="page">
    <PageHeader title="订单" description="仅展示当前登录用户的订单，点击行查看详情与物流轨迹">
      <el-button size="small" :loading="loading" @click="load">刷新</el-button>
    </PageHeader>

    <div class="panel">
      <div class="toolbar">
        <el-select v-model="status" placeholder="全部状态" clearable style="width: 160px" @change="search">
          <el-option
            v-for="option in statusOptions"
            :key="option.value"
            :label="option.label"
            :value="option.value"
          />
        </el-select>
        <span class="toolbar__spacer" />
        <span class="text-muted">共 {{ total }} 笔</span>
      </div>
    </div>

    <div class="panel panel--flush">
      <DataState
        :loading="loading"
        :error="error"
        :empty="!loading && !error && orders.length === 0"
        empty-text="还没有订单"
        empty-description="下单后可在这里查看订单与物流"
        @retry="load"
      >
        <el-table :data="orders" size="small" @row-click="openDetail">
          <el-table-column prop="orderNo" label="订单号" min-width="180">
            <template #default="{ row }">
              <span class="mono">{{ row.orderNo }}</span>
            </template>
          </el-table-column>
          <el-table-column label="状态" width="100">
            <template #default="{ row }">
              <el-tag size="small" :type="metaOf(ORDER_STATUS_META, row.status).tone" effect="plain">
                {{ metaOf(ORDER_STATUS_META, row.status).label }}
              </el-tag>
            </template>
          </el-table-column>
          <el-table-column label="实付金额" width="130" align="right">
            <template #default="{ row }">{{ formatMoney(row.payAmount) }}</template>
          </el-table-column>
          <el-table-column prop="receiverName" label="收货人" width="110" />
          <el-table-column label="件数" width="80" align="right">
            <template #default="{ row }">{{ countItems(row.items) }}</template>
          </el-table-column>
          <el-table-column label="下单时间" width="180">
            <template #default="{ row }">{{ formatDateTime(row.createdAt) }}</template>
          </el-table-column>
        </el-table>

        <div class="pager">
          <el-pagination
            layout="prev, pager, next, total"
            :total="total"
            :page-size="size"
            :current-page="page"
            background
            @current-change="onPageChange"
          />
        </div>
      </DataState>
    </div>

    <OrderDetailDrawer v-model:visible="drawerVisible" :order-no="activeOrderNo" />
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { listOrders } from '@/api/order'
import type { OrderItemVO, OrderStatus, OrderVO } from '@/types'
import { errorMessage } from '@/utils/guard'
import { ORDER_STATUS_META, formatDateTime, formatMoney, metaOf } from '@/utils/format'
import DataState from '@/components/common/DataState.vue'
import PageHeader from '@/components/common/PageHeader.vue'
import OrderDetailDrawer from '@/components/order/OrderDetailDrawer.vue'

const orders = ref<OrderVO[]>([])
const total = ref(0)
const page = ref(1)
const size = ref(10)
const status = ref<OrderStatus | ''>('')
const loading = ref(false)
const error = ref('')
const drawerVisible = ref(false)
const activeOrderNo = ref('')

const statusOptions = computed(() =>
  Object.entries(ORDER_STATUS_META).map(([value, meta]) => ({ value, label: meta.label })),
)

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const result = await listOrders({
      status: status.value || undefined,
      page: page.value,
      size: size.value,
    })
    orders.value = result.items ?? []
    total.value = result.total ?? 0
  } catch (err) {
    error.value = errorMessage(err, '订单列表加载失败')
    orders.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

function search(): void {
  page.value = 1
  void load()
}

function onPageChange(next: number): void {
  page.value = next
  void load()
}

function countItems(items: OrderItemVO[] | undefined): number {
  return (items ?? []).reduce((sum, item) => sum + (item.quantity || 0), 0)
}

function openDetail(row: OrderVO): void {
  activeOrderNo.value = row.orderNo
  drawerVisible.value = true
}

onMounted(load)
</script>

<style scoped lang="scss">
.pager {
  display: flex;
  justify-content: flex-end;
  padding: 12px 16px;
}
</style>
