package com.xingtu.agent.tool;

import com.xingtu.agent.infra.repo.ProductRepository;
import com.xingtu.agent.rag.LlmReranker;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 商品工具：search_products / get_product_detail / compare_products（全部 READ）。
 */
@Component
public class ProductTools {

    private static final List<String> AGENTS = List.of("SHOPPING");

    private final ProductRepository productRepository;
    private final LlmReranker reranker;

    public ProductTools(ToolRegistry registry, ProductRepository productRepository, LlmReranker reranker) {
        this.productRepository = productRepository;
        this.reranker = reranker;
        registry.register(new ToolRegistry.Definition("search_products",
                "按自然语言需求检索商品，参数 {query, topK?, maxPrice?, brands?[]}；返回 sku/title/price/score。",
                ToolRisk.READ, AGENTS, this::searchProducts));
        registry.register(new ToolRegistry.Definition("get_product_detail",
                "按 sku 查询商品详情，参数 {sku}。", ToolRisk.READ, AGENTS, this::getProductDetail));
        registry.register(new ToolRegistry.Definition("compare_products",
                "对比 2~4 个商品的关键参数，参数 {skus[]}。", ToolRisk.READ, AGENTS, this::compareProducts));
    }

    private ToolResult searchProducts(Map<String, Object> args, ToolContext context) {
        String query = ToolContext.str(args, "query", context.question());
        int topK = Math.max(1, Math.min(ToolContext.intVal(args, "topK", 5), 10));
        BigDecimal maxPrice = ToolContext.decimal(args, "maxPrice");
        if (maxPrice != null && maxPrice.compareTo(BigDecimal.ZERO) <= 0) {
            maxPrice = null;
        }
        List<String> brands = ToolContext.strList(args, "brands");

        List<ProductRepository.ProductRow> rows = productRepository.fullTextSearch(query, 30);
        List<LlmReranker.Candidate> candidates = new ArrayList<>();
        Map<Long, ProductRepository.ProductRow> byId = new LinkedHashMap<>();
        for (ProductRepository.ProductRow row : rows) {
            if (maxPrice != null && row.price() != null && row.price().compareTo(maxPrice) > 0) {
                continue;
            }
            if (!brands.isEmpty() && (row.brand() == null || !containsBrand(brands, row.brand()))) {
                continue;
            }
            byId.put(row.id(), row);
            candidates.add(new LlmReranker.Candidate(row.id(), row.categoryId(), row.title(),
                    row.title() + " " + safe(row.subtitle()) + " " + safe(row.brand()) + " "
                            + safe(row.description()), 0d));
        }
        List<LlmReranker.Ranked> ranked = reranker.rerank(query, candidates, topK);

        List<Map<String, Object>> items = new ArrayList<>();
        for (LlmReranker.Ranked hit : ranked) {
            ProductRepository.ProductRow row = byId.get(hit.chunkId());
            if (row == null) {
                continue;
            }
            Map<String, Object> item = new LinkedHashMap<>();
            item.put("sku", row.sku());
            item.put("title", row.title());
            item.put("price", row.price());
            item.put("brand", row.brand());
            item.put("rating", row.rating());
            item.put("stock", row.stock());
            item.put("score", hit.rerankScore());
            item.put("reason", reasonOf(row, maxPrice));
            items.add(item);
        }
        if (items.isEmpty()) {
            return ToolResult.fail("未找到匹配的商品，建议放宽价格或品牌条件");
        }
        StringBuilder summary = new StringBuilder("命中 ").append(items.size()).append(" 件商品: ");
        for (int i = 0; i < items.size(); i++) {
            if (i > 0) {
                summary.append("；");
            }
            summary.append(items.get(i).get("sku")).append(" ").append(items.get(i).get("title"))
                    .append(" ¥").append(items.get(i).get("price"));
        }
        return ToolResult.ok(summary.toString(), items);
    }

    private ToolResult getProductDetail(Map<String, Object> args, ToolContext context) {
        String sku = ToolContext.str(args, "sku", "");
        if (sku.isEmpty()) {
            return ToolResult.fail("缺少参数 sku");
        }
        ProductRepository.ProductRow row = productRepository.findBySku(sku);
        if (row == null) {
            return ToolResult.fail("商品不存在: " + sku);
        }
        Map<String, Object> item = new LinkedHashMap<>();
        item.put("sku", row.sku());
        item.put("title", row.title());
        item.put("subtitle", row.subtitle());
        item.put("brand", row.brand());
        item.put("price", row.price());
        item.put("originalPrice", row.originalPrice());
        item.put("stock", row.stock());
        item.put("rating", row.rating());
        item.put("sales", row.sales());
        item.put("description", row.description());
        item.put("imageUrl", row.imageUrl());
        return ToolResult.ok(row.sku() + " " + row.title() + " ¥" + row.price()
                + " 库存 " + row.stock() + " 评分 " + row.rating(), item);
    }

    private ToolResult compareProducts(Map<String, Object> args, ToolContext context) {
        List<String> skus = ToolContext.strList(args, "skus");
        if (skus.size() < 2) {
            return ToolResult.fail("至少需要 2 个 sku 才能对比");
        }
        List<ProductRepository.ProductRow> rows = productRepository.listBySkus(skus);
        if (rows.size() < 2) {
            return ToolResult.fail("可用商品不足 2 个，无法对比");
        }
        List<Map<String, Object>> items = new ArrayList<>();
        for (ProductRepository.ProductRow row : rows) {
            Map<String, Object> item = new LinkedHashMap<>();
            item.put("sku", row.sku());
            item.put("title", row.title());
            item.put("brand", row.brand());
            item.put("price", row.price());
            item.put("rating", row.rating());
            item.put("sales", row.sales());
            item.put("stock", row.stock());
            items.add(item);
        }
        items.sort(Comparator.comparing(item -> String.valueOf(item.get("sku"))));
        StringBuilder summary = new StringBuilder("对比 ").append(items.size()).append(" 件商品: ");
        for (Map<String, Object> item : items) {
            summary.append(item.get("sku")).append("(¥").append(item.get("price")).append(") ");
        }
        return ToolResult.ok(summary.toString().trim(), items);
    }

    private boolean containsBrand(List<String> brands, String brand) {
        for (String item : brands) {
            if (brand.equalsIgnoreCase(item) || brand.contains(item)) {
                return true;
            }
        }
        return false;
    }

    private String reasonOf(ProductRepository.ProductRow row, BigDecimal maxPrice) {
        StringBuilder sb = new StringBuilder();
        if (row.rating() != null && row.rating().doubleValue() >= 4.5d) {
            sb.append("评分高");
        }
        if (row.sales() > 500) {
            sb.append(sb.length() > 0 ? "、销量领先" : "销量领先");
        }
        if (maxPrice != null && row.price() != null && row.price().compareTo(maxPrice) <= 0) {
            sb.append(sb.length() > 0 ? "、在预算内" : "在预算内");
        }
        if (sb.length() == 0) {
            sb.append("与需求匹配");
        }
        return sb.toString();
    }

    private String safe(String text) {
        return text == null ? "" : text;
    }
}
