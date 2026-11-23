package com.xingtu.agent.common;

import java.security.SecureRandom;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;
import java.util.UUID;

/**
 * ID 生成：traceId / 订单号 / 退款单号 / 幂等键。全部无外部依赖，便于离线测试。
 */
public final class Ids {

    private static final DateTimeFormatter TS = DateTimeFormatter.ofPattern("yyyyMMddHHmmss");
    private static final SecureRandom RANDOM = new SecureRandom();
    private static final char[] HEX = "0123456789abcdef".toCharArray();

    private Ids() {
    }

    public static String newTraceId() {
        return UUID.randomUUID().toString().replace("-", "");
    }

    public static String shortUuid() {
        return UUID.randomUUID().toString().replace("-", "").substring(0, 12);
    }

    public static String spanId() {
        byte[] bytes = new byte[8];
        RANDOM.nextBytes(bytes);
        StringBuilder sb = new StringBuilder(16);
        for (byte b : bytes) {
            sb.append(HEX[(b >> 4) & 0x0F]).append(HEX[b & 0x0F]);
        }
        return sb.toString();
    }

    public static String orderNo() {
        return "SO" + LocalDateTime.now().format(TS) + digits(4);
    }

    public static String refundNo() {
        return "RF" + LocalDateTime.now().format(TS) + digits(4);
    }

    public static String idempotencyKey() {
        return "idem-" + UUID.randomUUID().toString().replace("-", "");
    }

    public static String uuid() {
        return UUID.randomUUID().toString();
    }

    private static String digits(int count) {
        StringBuilder sb = new StringBuilder(count);
        for (int i = 0; i < count; i++) {
            sb.append(RANDOM.nextInt(10));
        }
        return sb.toString();
    }
}
