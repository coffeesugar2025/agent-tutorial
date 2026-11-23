package com.xingtu.agent.common;

/**
 * 轻量 token 估算：中文按 1 字 ≈ 1 token，其它字符按 4 字符 ≈ 1 token（与 Python 端回退策略一致）。
 * 真实供应商返回 usage 时以供应商为准。
 */
public final class TokenEstimator {

    private TokenEstimator() {
    }

    public static int estimate(String text) {
        if (text == null || text.isEmpty()) {
            return 0;
        }
        int cjk = 0;
        int other = 0;
        for (int i = 0; i < text.length(); i++) {
            char c = text.charAt(i);
            if (isCjk(c)) {
                cjk++;
            } else {
                other++;
            }
        }
        int otherTokens = (other + 3) / 4;
        return Math.max(1, cjk + otherTokens);
    }

    public static int estimateAll(Iterable<String> texts) {
        int total = 0;
        if (texts != null) {
            for (String t : texts) {
                total += estimate(t);
            }
        }
        return total;
    }

    private static boolean isCjk(char c) {
        return (c >= 0x4E00 && c <= 0x9FFF)
                || (c >= 0x3400 && c <= 0x4DBF)
                || (c >= 0x3000 && c <= 0x303F)
                || (c >= 0xFF00 && c <= 0xFFEF);
    }
}
