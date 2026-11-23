package com.xingtu.agent.common;

import java.util.List;

/**
 * 统一分页结构：{"items":[],"total":0,"page":1,"size":20}。
 */
public record PageResult<T>(List<T> items, long total, int page, int size) {

    public static <T> PageResult<T> of(List<T> items, long total, int page, int size) {
        return new PageResult<>(items == null ? List.of() : items, total, page, size);
    }

    public static <T> PageResult<T> empty(int page, int size) {
        return new PageResult<>(List.of(), 0L, page, size);
    }

    public static int normalizePage(Integer page) {
        return page == null || page < 1 ? 1 : page;
    }

    public static int normalizeSize(Integer size, int max) {
        if (size == null || size < 1) {
            return 20;
        }
        return Math.min(size, max);
    }

    public int offset() {
        return (page - 1) * size;
    }
}
