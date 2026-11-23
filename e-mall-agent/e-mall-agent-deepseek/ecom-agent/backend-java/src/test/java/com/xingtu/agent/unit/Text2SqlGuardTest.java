package com.xingtu.agent.unit;

import com.xingtu.agent.common.BizException;
import com.xingtu.agent.tool.Text2SqlGuard;
import org.junit.jupiter.api.Test;

import java.util.List;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertThrows;
import static org.junit.jupiter.api.Assertions.assertTrue;

class Text2SqlGuardTest {

    private final Text2SqlGuard guard = new Text2SqlGuard();

    @Test
    void acceptsReadOnlySelectAndEnforcesLimit() {
        String sql = guard.validate("select id, title from product where price < 5000");
        assertTrue(sql.endsWith("LIMIT 200"));
        assertEquals("select id, title from product where price < 5000 LIMIT 200", sql);
    }

    @Test
    void keepsExistingLimitAndAllowsCreatedAtColumn() {
        assertEquals("SELECT * FROM product LIMIT 10",
                guard.validate("SELECT * FROM product LIMIT 10"));
        // created_at 不能被 create 关键词误杀
        String sql = guard.validate("select id from product where created_at > '2026-01-01'");
        assertTrue(sql.contains("created_at"));
    }

    @Test
    void rejectsDmlAndDdl() {
        assertThrows(BizException.class, () -> guard.validate("DELETE FROM product WHERE id = 1"));
        assertThrows(BizException.class, () -> guard.validate("update product set price = 1"));
        assertThrows(BizException.class, () -> guard.validate("drop table product"));
    }

    @Test
    void rejectsCommentsMultiStatementAndDelayedFunctions() {
        assertThrows(BizException.class, () -> guard.validate("select id from product -- leak"));
        assertThrows(BizException.class, () -> guard.validate("select /*x*/ id from product"));
        assertThrows(BizException.class,
                () -> guard.validate("select id from product; select id from category"));
        assertThrows(BizException.class, () -> guard.validate("select sleep(1), id from product"));
    }

    @Test
    void rejectsUnionSelectAndUnknownTables() {
        assertThrows(BizException.class,
                () -> guard.validate("select id from product union select id from category"));
        assertThrows(BizException.class, () -> guard.validate("select * from sys_user"));
        assertThrows(BizException.class, () -> guard.validate("select * from information_schema.tables"));
    }

    @Test
    void rejectsBlankAndNonSelect() {
        assertThrows(BizException.class, () -> guard.validate(null));
        assertThrows(BizException.class, () -> guard.validate("   "));
        assertThrows(BizException.class, () -> guard.validate("show tables"));
    }

    @Test
    void exposesTablesAndReadOnlyFlag() {
        List<String> tables = guard.tables("select * from product p join category c on p.category_id = c.id");
        assertEquals(List.of("product", "category"), tables);
        assertTrue(guard.isReadOnlySelect("select id from product"));
        assertFalse(guard.isReadOnlySelect("select id from product;"));
        assertFalse(guard.isReadOnlySelect(null));
    }
}
