<template>
  <div class="page">
    <PageHeader title="商品" description="关键词 + 价格区间检索商品，点击行查看详情">
      <el-button size="small" :loading="loading" @click="load">刷新</el-button>
    </PageHeader>

    <div class="panel">
      <div class="toolbar">
        <el-input
          v-model="filters.keyword"
          placeholder="搜索标题 / SKU"
          clearable
          style="width: 240px"
          @keyup.enter="search"
        />
        <el-input-number
          v-model="filters.minPrice"
          :min="0"
          :controls="false"
          placeholder="最低价"
          style="width: 110px"
        />
        <span class="text-muted">-</span>
        <el-input-number
          v-model="filters.maxPrice"
          :min="0"
          :controls="false"
          placeholder="最高价"
          style="width: 110px"
        />
        <el-button type="primary" size="small" @click="search">查询</el-button>
        <el-button size="small" @click="reset">重置</el-button>
        <span class="toolbar__spacer" />
        <span class="text-muted">共 {{ total }} 件</span>
      </div>
    </div>

    <div class="panel panel--flush">
      <DataState
        :loading="loading"
        :error="error"
        :empty="!loading && !error && items.length === 0"
        empty-text="没有匹配的商品"
        @retry="load"
      >
        <el-table :data="items" size="small" @row-click="openDetail">
          <el-table-column label="商品" min-width="260">
            <template #default="{ row }">
              <div class="product-cell">
                <el-image v-if="row.imageUrl" :src="row.imageUrl" fit="cover" class="product-cell__img" />
                <div v-else class="product-cell__img product-cell__img--empty">无图</div>
                <div class="product-cell__text">
                  <div class="ellipsis">{{ row.title }}</div>
                  <div class="product-cell__sku mono">{{ row.sku }}</div>
                </div>
              </div>
            </template>
          </el-table-column>
          <el-table-column prop="brand" label="品牌" width="110" />
          <el-table-column prop="categoryName" label="分类" width="110" />
          <el-table-column label="价格" width="130" align="right">
            <template #default="{ row }">
              <span class="text-strong">{{ formatMoney(row.price) }}</span>
            </template>
          </el-table-column>
          <el-table-column prop="stock" label="库存" width="80" align="right" />
          <el-table-column label="评分" width="80" align="right">
            <template #default="{ row }">{{ formatScore(row.rating, 1) }}</template>
          </el-table-column>
          <el-table-column label="销量" width="90" align="right">
            <template #default="{ row }">{{ formatNumber(row.sales) }}</template>
          </el-table-column>
          <el-table-column label="状态" width="90">
            <template #default="{ row }">
              <el-tag size="small" :type="row.status === 1 ? 'success' : 'info'" effect="plain">
                {{ row.status === 1 ? '在售' : '下架' }}
              </el-tag>
            </template>
          </el-table-column>
        </el-table>

        <div class="pager">
          <el-pagination
            layout="prev, pager, next, total"
            :total="total"
            :page-size="filters.size"
            :current-page="filters.page"
            background
            @current-change="onPageChange"
          />
        </div>
      </DataState>
    </div>

    <ProductDetailDrawer v-model:visible="drawerVisible" :sku="activeSku" />
  </div>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue'
import { listProducts } from '@/api/product'
import type { ProductVO } from '@/types'
import { errorMessage } from '@/utils/guard'
import { formatMoney, formatNumber, formatScore } from '@/utils/format'
import DataState from '@/components/common/DataState.vue'
import PageHeader from '@/components/common/PageHeader.vue'
import ProductDetailDrawer from '@/components/product/ProductDetailDrawer.vue'

const items = ref<ProductVO[]>([])
const total = ref(0)
const loading = ref(false)
const error = ref('')
const drawerVisible = ref(false)
const activeSku = ref('')

const filters = reactive<{
  keyword: string
  minPrice: number | undefined
  maxPrice: number | undefined
  page: number
  size: number
}>({
  keyword: '',
  minPrice: undefined,
  maxPrice: undefined,
  page: 1,
  size: 10,
})

async function load(): Promise<void> {
  loading.value = true
  error.value = ''
  try {
    const result = await listProducts({
      keyword: filters.keyword.trim() || undefined,
      minPrice: filters.minPrice,
      maxPrice: filters.maxPrice,
      page: filters.page,
      size: filters.size,
    })
    items.value = result.items ?? []
    total.value = result.total ?? 0
  } catch (err) {
    error.value = errorMessage(err, '商品列表加载失败')
    items.value = []
    total.value = 0
  } finally {
    loading.value = false
  }
}

function search(): void {
  filters.page = 1
  void load()
}

function reset(): void {
  filters.keyword = ''
  filters.minPrice = undefined
  filters.maxPrice = undefined
  filters.page = 1
  void load()
}

function onPageChange(page: number): void {
  filters.page = page
  void load()
}

function openDetail(row: ProductVO): void {
  activeSku.value = row.sku
  drawerVisible.value = true
}

onMounted(load)
</script>

<style scoped lang="scss">
.product-cell {
  display: flex;
  align-items: center;
  gap: 10px;

  &__img {
    width: 40px;
    height: 40px;
    border-radius: 6px;
    flex-shrink: 0;
  }

  &__img--empty {
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 10px;
    color: var(--ecom-text-placeholder);
    background: #f1f5f9;
  }

  &__text {
    min-width: 0;
    font-size: 13px;
  }

  &__sku {
    margin-top: 2px;
    font-size: 11px;
    color: var(--ecom-text-placeholder);
  }
}

.pager {
  display: flex;
  justify-content: flex-end;
  padding: 12px 16px;
}
</style>
