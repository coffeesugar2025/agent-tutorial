package com.xingtu.agent.api;

import com.xingtu.agent.api.dto.ProductDtos;
import com.xingtu.agent.common.ApiResponse;
import com.xingtu.agent.common.BizException;
import com.xingtu.agent.common.JsonUtil;
import com.xingtu.agent.common.PageResult;
import com.xingtu.agent.infra.repo.ProductRepository;
import com.xingtu.agent.rag.SparseEncoder;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashSet;
import java.util.List;
import java.util.Locale;
import java.util.Set;

/**
 * 商品接口（docs/03-API契约.md 第 3 节）。
 */
@RestController
@RequestMapping("/api/v1/products")
public class ProductController {

    private static final int MAX_PAGE_SIZE = 100;
    private static final int MAX_TOP_K = 20;

    private final ProductRepository productRepository;
    private final SparseEncoder sparseEncoder;

    public ProductController(ProductRepository productRepository, SparseEncoder sparseEncoder) {
        this.productRepository = productRepository;
        this.sparseEncoder = sparseEncoder;
    }

    @GetMapping
    public ApiResponse<PageResult<ProductDtos.ProductVO>> list(
            @RequestParam(value = "keyword", required = false) String keyword,
            @RequestParam(value = "categoryId", required = false) Long categoryId,
            @RequestParam(value = "minPrice", required = false) BigDecimal minPrice,
            @RequestParam(value = "maxPrice", required = false) BigDecimal maxPrice,
            @RequestParam(value = "page", defaultValue = "1") int page,
            @RequestParam(value = "size", defaultValue = "20") int size) {
        int normalizedPage = PageResult.normalizePage(page);
        int normalizedSize = PageResult.normalizeSize(size, MAX_PAGE_SIZE);
        PageResult<ProductRepository.ProductRow> rows = productRepository.search(keyword, categoryId,
                minPrice, maxPrice, normalizedPage, normalizedSize);
        List<ProductDtos.ProductVO> items = new ArrayList<>(rows.items().size());
        for (ProductRepository.ProductRow row : rows.items()) {
            items.add(toVO(row, false));
        }
        return ApiResponse.ok(PageResult.of(items, rows.total(), normalizedPage, normalizedSize));
    }

    @GetMapping("/{sku}")
    public ApiResponse<ProductDtos.ProductVO> detail(@PathVariable("sku") String sku) {
        if (sku == null || sku.isBlank()) {
            throw BizException.validation("sku 不能为空");
        }
        ProductRepository.ProductRow row = productRepository.findBySku(sku.trim());
        if (row == null) {
            throw BizException.notFound("商品不存在: " + sku);
        }
        return ApiResponse.ok(toVO(row, true));
    }

    /**
     * 语义化商品检索：MySQL FULLTEXT 召回 + 关键词覆盖度打分。
     * strategy 固定 hybrid：FULLTEXT 索引缺失时 ProductRepository 内部已降级到 LIKE。
     */
    @PostMapping("/search")
    public ApiResponse<ProductDtos.ProductSearchVO> search(
            @RequestBody(required = false) ProductDtos.ProductSearchReq req) {
        if (req == null || req.query() == null || req.query().isBlank()) {
            throw BizException.validation("query 不能为空");
        }
        String query = req.query().trim();
        int topK = req.topK() == null ? 5 : Math.max(1, Math.min(req.topK(), MAX_TOP_K));
        BigDecimal maxPrice = req.maxPrice();
        List<String> brands = req.brands();
        int candidateLimit = Math.max(20, topK * 4);

        List<ProductRepository.ProductRow> candidates = productRepository.fullTextSearch(query, candidateLimit);
        if (candidates.isEmpty()) {
            candidates = productRepository.search(query, null, null, maxPrice, 1, candidateLimit).items();
        }

        List<ProductDtos.ProductSearchItemVO> items = new ArrayList<>();
        for (ProductRepository.ProductRow row : candidates) {
            if (maxPrice != null && row.price() != null && row.price().compareTo(maxPrice) > 0) {
                continue;
            }
            if (brands != null && !brands.isEmpty() && !matchesBrand(row.brand(), brands)) {
                continue;
            }
            double coverage = coverage(query, searchableText(row));
            double salesScore = Math.min(1d, Math.max(0, row.sales()) / 10000d);
            double ratingScore = row.rating() == null ? 0d
                    : Math.min(1d, Math.max(0d, row.rating().doubleValue() / 5d));
            double score = round4(coverage * 0.7d + salesScore * 0.2d + ratingScore * 0.1d);
            items.add(new ProductDtos.ProductSearchItemVO(row.sku(), row.title(), row.price(), score,
                    reason(query, coverage, row)));
        }
        items.sort(Comparator.comparingDouble(ProductDtos.ProductSearchItemVO::score).reversed());
        List<ProductDtos.ProductSearchItemVO> limited = items.size() > topK
                ? new ArrayList<>(items.subList(0, topK)) : items;
        return ApiResponse.ok(new ProductDtos.ProductSearchVO(limited, "hybrid"));
    }

    private ProductDtos.ProductVO toVO(ProductRepository.ProductRow row, boolean withDescription) {
        return new ProductDtos.ProductVO(row.id(), row.sku(), row.title(), row.subtitle(), row.brand(),
                row.categoryId(), row.categoryName(), row.price(), row.originalPrice(), row.stock(),
                row.rating(), row.sales(), row.imageUrl(), JsonUtil.parseMap(row.attrs()), row.status(),
                withDescription ? row.description() : null);
    }

    private String searchableText(ProductRepository.ProductRow row) {
        StringBuilder sb = new StringBuilder();
        sb.append(row.title() == null ? "" : row.title()).append(' ');
        sb.append(row.subtitle() == null ? "" : row.subtitle()).append(' ');
        sb.append(row.brand() == null ? "" : row.brand()).append(' ');
        sb.append(row.description() == null ? "" : row.description());
        return sb.toString();
    }

    /** 查询词在商品文本中的覆盖度（0~1），与切片检索使用同一分词口径。 */
    private double coverage(String query, String text) {
        Set<String> queryTerms = new LinkedHashSet<>(sparseEncoder.terms(query));
        if (queryTerms.isEmpty() || text == null || text.isEmpty()) {
            return 0d;
        }
        Set<String> documentTerms = new LinkedHashSet<>(sparseEncoder.terms(text));
        int hit = 0;
        for (String term : queryTerms) {
            if (documentTerms.contains(term)) {
                hit++;
            }
        }
        return (double) hit / queryTerms.size();
    }

    private boolean matchesBrand(String brand, List<String> brands) {
        if (brand == null) {
            return false;
        }
        String normalized = brand.trim().toLowerCase(Locale.ROOT);
        for (String candidate : brands) {
            if (candidate == null || candidate.isBlank()) {
                continue;
            }
            String wanted = candidate.trim().toLowerCase(Locale.ROOT);
            if (normalized.equals(wanted) || normalized.contains(wanted)) {
                return true;
            }
        }
        return false;
    }

    private String reason(String query, double coverage, ProductRepository.ProductRow row) {
        StringBuilder sb = new StringBuilder();
        if (coverage > 0d) {
            sb.append("与「").append(query).append("」的关键词匹配度 ")
                    .append(Math.round(coverage * 100d)).append('%');
        } else {
            sb.append("同类热销商品");
        }
        sb.append("；销量 ").append(row.sales());
        if (row.rating() != null) {
            sb.append("；评分 ").append(row.rating());
        }
        if (row.price() != null) {
            sb.append("；售价 ").append(row.price());
        }
        return sb.toString();
    }

    private double round4(double value) {
        return Math.round(value * 10000d) / 10000d;
    }
}
