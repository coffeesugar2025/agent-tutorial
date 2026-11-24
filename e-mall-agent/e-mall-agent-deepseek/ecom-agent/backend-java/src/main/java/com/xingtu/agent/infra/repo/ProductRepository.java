package com.xingtu.agent.infra.repo;

// ═══════ 文件级能力标注 ═══════
// [CAP-05] 工具治理  |  [CAP-12] 检索增强 RAG  （支撑）
// 职责：商品表访问（product / category），含 MySQL FULLTEXT(ngram) 降级检索
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

import com.xingtu.agent.common.PageResult;
import com.xingtu.agent.infra.JdbcSupport;
import org.springframework.dao.DataAccessException;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.stereotype.Repository;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;

/**
 * 商品表访问（product / category），含 MySQL FULLTEXT(ngram) 降级检索。
 */
@Repository
public class ProductRepository {

    public record ProductRow(long id, String sku, String title, String subtitle, String brand,
                             long categoryId, String categoryName, BigDecimal price, BigDecimal originalPrice,
                             int stock, BigDecimal rating, int sales, String imageUrl, String attrs,
                             int status, String description) {
    }

    private static final String SELECT = "SELECT p.id, p.sku, p.title, p.subtitle, p.brand, p.category_id, "
            + "c.name AS category_name, p.price, p.original_price, p.stock, p.rating, p.sales, "
            + "p.image_url, p.attrs, p.status, p.description "
            + "FROM product p LEFT JOIN category c ON c.id = p.category_id ";

    private final JdbcTemplate jdbc;

    public ProductRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public PageResult<ProductRow> search(String keyword, Long categoryId, BigDecimal minPrice,
                                         BigDecimal maxPrice, int page, int size) {
        StringBuilder where = new StringBuilder(" WHERE p.status = 1");
        List<Object> args = new ArrayList<>();
        if (keyword != null && !keyword.isBlank()) {
            where.append(" AND (p.title LIKE ? OR p.subtitle LIKE ? OR p.brand LIKE ?)");
            String like = "%" + keyword.trim() + "%";
            args.add(like);
            args.add(like);
            args.add(like);
        }
        if (categoryId != null && categoryId > 0) {
            where.append(" AND p.category_id = ?");
            args.add(categoryId);
        }
        if (minPrice != null) {
            where.append(" AND p.price >= ?");
            args.add(minPrice);
        }
        if (maxPrice != null) {
            where.append(" AND p.price <= ?");
            args.add(maxPrice);
        }

        long total = JdbcSupport.count(jdbc, "SELECT COUNT(*) FROM product p " + where, args.toArray());

        List<Object> pageArgs = new ArrayList<>(args);
        pageArgs.add(size);
        pageArgs.add((page - 1) * size);
        List<ProductRow> rows = JdbcSupport.list(jdbc,
                SELECT + where + " ORDER BY p.sales DESC, p.id DESC LIMIT ? OFFSET ?",
                mapper(), pageArgs.toArray());
        return PageResult.of(rows, total, page, size);
    }

    public ProductRow findBySku(String sku) {
        return JdbcSupport.one(jdbc, SELECT + " WHERE p.sku = ?", mapper(), sku);
    }

    public ProductRow findById(long id) {
        return JdbcSupport.one(jdbc, SELECT + " WHERE p.id = ?", mapper(), id);
    }

    public List<ProductRow> listBySkus(List<String> skus) {
        if (skus == null || skus.isEmpty()) {
            return List.of();
        }
        StringBuilder sql = new StringBuilder(SELECT).append(" WHERE p.sku IN (");
        List<Object> args = new ArrayList<>();
        for (int i = 0; i < skus.size(); i++) {
            sql.append(i == 0 ? "?" : ",?");
            args.add(skus.get(i));
        }
        sql.append(")");
        return JdbcSupport.list(jdbc, sql.toString(), mapper(), args.toArray());
    }

    /**
     * MySQL FULLTEXT(ngram) 检索；索引不可用（例如未执行 init SQL）时降级为 LIKE。
     */
    public List<ProductRow> fullTextSearch(String keyword, int limit) {
        if (keyword == null || keyword.isBlank()) {
            return List.of();
        }
        String matchSql = SELECT
                + " WHERE p.status = 1 AND MATCH(p.title, p.subtitle, p.brand, p.search_text) "
                + "AGAINST (? IN NATURAL LANGUAGE MODE) ORDER BY p.sales DESC LIMIT ?";
        try {
            List<ProductRow> rows = JdbcSupport.list(jdbc, matchSql, mapper(), keyword.trim(), limit);
            if (!rows.isEmpty()) {
                return rows;
            }
        } catch (DataAccessException ignored) {
            // FULLTEXT 索引缺失时静默降级
        }
        return JdbcSupport.list(jdbc,
                SELECT + " WHERE p.status = 1 AND (p.title LIKE ? OR p.subtitle LIKE ? OR p.brand LIKE ?) "
                        + "ORDER BY p.sales DESC LIMIT ?",
                mapper(), "%" + keyword.trim() + "%", "%" + keyword.trim() + "%",
                "%" + keyword.trim() + "%", limit);
    }

    private RowMapper<ProductRow> mapper() {
        return (rs, rowNum) -> new ProductRow(
                JdbcSupport.lng(rs, "id"),
                JdbcSupport.str(rs, "sku"),
                JdbcSupport.str(rs, "title"),
                JdbcSupport.str(rs, "subtitle"),
                JdbcSupport.str(rs, "brand"),
                JdbcSupport.lng(rs, "category_id"),
                JdbcSupport.str(rs, "category_name"),
                JdbcSupport.dec(rs, "price"),
                JdbcSupport.dec(rs, "original_price"),
                JdbcSupport.intVal(rs, "stock"),
                JdbcSupport.dec(rs, "rating"),
                JdbcSupport.intVal(rs, "sales"),
                JdbcSupport.str(rs, "image_url"),
                JdbcSupport.str(rs, "attrs"),
                JdbcSupport.intVal(rs, "status"),
                JdbcSupport.str(rs, "description"));
    }
}
