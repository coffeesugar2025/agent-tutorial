<template>
  <el-drawer
    :model-value="visible"
    title="商品详情"
    size="480px"
    @update:model-value="onVisibleChange"
  >
    <DataState :loading="loading" :error="error" :empty="!loading && !product && !error" empty-text="暂未选择商品" @retry="load">
      <div v-if="product" class="product-detail">
        <el-image v-if="product.imageUrl" :src="product.imageUrl" fit="cover" class="product-detail__image">
          <template #error>
            <div class="product-detail__image-fallback">无图</div>
          </template>
        </el-image>
        <div v-else class="product-detail__image-fallback">无图</div>

        <h3 class="product-detail__title">{{ product.title }}</h3>
        <p v-if="product.subtitle" class="product-detail__subtitle">{{ product.subtitle }}</p>

        <div class="product-detail__price-row">
          <span class="product-detail__price">{{ formatMoney(product.price) }}</span>
          <span v-if="product.originalPrice" class="product-detail__origin">
            {{ formatMoney(product.originalPrice) }}
          </span>
          <el-tag size="small" :type="product.status === 1 ? 'success' : 'info'" effect="plain">
            {{ product.status === 1 ? '在售' : '已下架' }}
          </el-tag>
        </div>

        <el-descriptions :column="2" border size="small" class="mt-12">
          <el-descriptions-item label="SKU">{{ product.sku }}</el-descriptions-item>
          <el-descriptions-item label="品牌">{{ product.brand || '—' }}</el-descriptions-item>
          <el-descriptions-item label="分类">{{ product.categoryName || '—' }}</el-descriptions-item>
          <el-descriptions-item label="库存">{{ product.stock }}</el-descriptions-item>
          <el-descriptions-item label="评分">{{ formatScore(product.rating, 1) }}</el-descriptions-item>
          <el-descriptions-item label="销量">{{ formatNumber(product.sales) }}</el-descriptions-item>
        </el-descriptions>

        <template v-if="attrEntries.length">
          <h4 class="product-detail__section">商品属性</h4>
          <el-table :data="attrEntries" size="small" border>
            <el-table-column prop="key" label="属性" width="140" />
            <el-table-column prop="value" label="值" />
          </el-table>
        </template>

        <template v-if="product.description">
          <h4 class="product-detail__section">商品描述</h4>
          <div class="markdown-body" v-html="descriptionHtml" />
        </template>
      </div>
    </DataState>
  </el-drawer>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { getProduct } from '@/api/product'
import type { ProductVO } from '@/types'
import { errorMessage } from '@/utils/guard'
import { formatMoney, formatNumber, formatScore } from '@/utils/format'
import { renderMarkdown } from '@/utils/markdown'
import DataState from '@/components/common/DataState.vue'

const props = defineProps<{ visible: boolean; sku: string }>()
const emit = defineEmits<{ 'update:visible': [visible: boolean] }>()

const product = ref<ProductVO | null>(null)
const loading = ref(false)
const error = ref('')

const attrEntries = computed(() =>
  Object.entries(product.value?.attrs ?? {}).map(([key, value]) => ({ key, value: String(value) })),
)
const descriptionHtml = computed(() => renderMarkdown(product.value?.description ?? ''))

async function load(): Promise<void> {
  if (!props.sku) return
  loading.value = true
  error.value = ''
  try {
    product.value = await getProduct(props.sku)
  } catch (err) {
    error.value = errorMessage(err, '商品详情加载失败')
    product.value = null
  } finally {
    loading.value = false
  }
}

function onVisibleChange(value: boolean): void {
  emit('update:visible', value)
}

watch(
  () => [props.visible, props.sku] as const,
  ([visible, sku]) => {
    if (visible && sku) void load()
  },
  { immediate: true },
)
</script>

<style scoped lang="scss">
.product-detail {
  &__image,
  &__image-fallback {
    width: 100%;
    height: 200px;
    border-radius: 10px;
    object-fit: cover;
  }

  &__image-fallback {
    display: flex;
    align-items: center;
    justify-content: center;
    font-size: 13px;
    color: var(--ecom-text-placeholder);
    background: #f1f5f9;
  }

  &__title {
    margin: 12px 0 4px;
    font-size: 16px;
    font-weight: 600;
  }

  &__subtitle {
    margin: 0;
    font-size: 13px;
    color: var(--ecom-text-secondary);
  }

  &__price-row {
    display: flex;
    align-items: baseline;
    gap: 10px;
    margin-top: 10px;
  }

  &__price {
    font-size: 22px;
    font-weight: 600;
    color: var(--ecom-danger);
  }

  &__origin {
    font-size: 13px;
    color: var(--ecom-text-placeholder);
    text-decoration: line-through;
  }

  &__section {
    margin: 18px 0 8px;
    font-size: 14px;
    font-weight: 600;
  }
}
</style>
