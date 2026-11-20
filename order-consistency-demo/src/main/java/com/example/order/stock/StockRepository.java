package com.example.order.stock;

import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Repository;

@Repository
public class StockRepository {

    private final JdbcTemplate jdbc;

    public StockRepository(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    /**
     * 条件更新是防超卖的全部秘密：行锁 + WHERE available >= ? 原子完成，
     * affected rows 是唯一成功判据。绝不在 Java 里先 SELECT 再 UPDATE。
     */
    public boolean deduct(Long skuId, int qty) {
        int n = jdbc.update("""
                UPDATE t_sku_stock
                   SET available = available - ?, version = version + 1
                 WHERE sku_id = ? AND available >= ?
                """, qty, skuId, qty);
        return n == 1;
    }
}
