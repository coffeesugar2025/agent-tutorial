package com.xingtu.agent.unit;

// ═══════ 文件级能力标注 ═══════
// [CAP-17] 评测与迭代  （支撑）
// 职责：PiiMaskerTest
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

import com.xingtu.agent.security.PiiMasker;
import org.junit.jupiter.api.Test;

import static org.junit.jupiter.api.Assertions.assertEquals;
import static org.junit.jupiter.api.Assertions.assertFalse;
import static org.junit.jupiter.api.Assertions.assertNull;
import static org.junit.jupiter.api.Assertions.assertTrue;

class PiiMaskerTest {

    private final PiiMasker masker = new PiiMasker();

    @Test
    void masksPhoneKeepingPrefixAndSuffix() {
        assertEquals("138****8888", masker.maskPhone("13812348888"));
        assertNull(masker.maskPhone(null));
    }

    @Test
    void masksEmailKeepingFirstThreeChars() {
        assertEquals("ali***@xingtu.example.com", masker.maskEmail("alice@xingtu.example.com"));
        assertEquals("***", masker.maskEmail("not-an-email"));
    }

    @Test
    void masksIdCardAndBankCard() {
        assertEquals("3101**********1234", masker.maskIdCard("310101199001011234"));
        assertEquals("6222********7890", masker.maskBankCard("6222021234567890"));
    }

    @Test
    void masksAddress() {
        assertEquals("上海市浦东新****", masker.maskAddress("上海市浦东新区世纪大道100号"));
        assertEquals("****", masker.maskAddress("短地址"));
    }

    @Test
    void maskAllScrubsPhoneAndEmailInFreeText() {
        String masked = masker.maskAll("手机号 13812348888，邮箱 alice@xingtu.example.com");
        assertTrue(masked.contains("138****8888"));
        assertTrue(masked.contains("ali***@xingtu.example.com"));
        assertFalse(masked.contains("13812348888"));
    }

    @Test
    void piiDetectionWorks() {
        assertTrue(masker.containsPii("联系电话 13812348888"));
        assertFalse(masker.containsPii("你好，我想咨询退货政策"));
        assertFalse(masker.containsPii(null));
    }
}
