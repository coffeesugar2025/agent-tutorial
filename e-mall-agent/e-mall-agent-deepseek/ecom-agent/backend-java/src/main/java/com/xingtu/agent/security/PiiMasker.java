package com.xingtu.agent.security;

import org.springframework.stereotype.Component;

import java.util.regex.Matcher;
import java.util.regex.Pattern;

/**
 * PII 脱敏：手机号 / 邮箱 / 身份证 / 银行卡 / 收货地址。
 * 契约示例：138****8888。
 */
@Component
public class PiiMasker {

    private static final Pattern PHONE = Pattern.compile("(1[3-9]\\d)(\\d{4})(\\d{4})");
    private static final Pattern EMAIL = Pattern.compile("([A-Za-z0-9._%+-]{1,3})[A-Za-z0-9._%+-]*(@[A-Za-z0-9.-]+\\.[A-Za-z]{2,})");
    private static final Pattern ID_CARD = Pattern.compile("(\\d{4})\\d{10}(\\d{3}[0-9Xx])");
    private static final Pattern BANK_CARD = Pattern.compile("\\b(\\d{4})\\d{8,11}(\\d{4})\\b");

    public String maskPhone(String phone) {
        if (phone == null || phone.isBlank()) {
            return phone;
        }
        Matcher matcher = PHONE.matcher(phone);
        if (matcher.find()) {
            return matcher.replaceAll("$1****$3");
        }
        if (phone.length() >= 7) {
            return phone.substring(0, 3) + "****" + phone.substring(phone.length() - 4);
        }
        return "****";
    }

    public String maskEmail(String email) {
        if (email == null || email.isBlank()) {
            return email;
        }
        Matcher matcher = EMAIL.matcher(email);
        if (matcher.find()) {
            return matcher.replaceAll("$1***$2");
        }
        return "***";
    }

    public String maskIdCard(String idCard) {
        if (idCard == null || idCard.isBlank()) {
            return idCard;
        }
        Matcher matcher = ID_CARD.matcher(idCard);
        if (matcher.find()) {
            return matcher.replaceAll("$1**********$2");
        }
        return idCard.length() <= 6 ? "****" : idCard.substring(0, 4) + "**********"
                + idCard.substring(idCard.length() - 3);
    }

    public String maskBankCard(String card) {
        if (card == null || card.isBlank()) {
            return card;
        }
        Matcher matcher = BANK_CARD.matcher(card);
        if (matcher.find()) {
            return matcher.replaceAll("$1********$2");
        }
        return "****";
    }

    public String maskAddress(String address) {
        if (address == null || address.isBlank()) {
            return address;
        }
        String trimmed = address.trim();
        if (trimmed.length() <= 6) {
            return "****";
        }
        return trimmed.substring(0, Math.min(6, trimmed.length())) + "****";
    }

    /** 全文扫描脱敏，用于日志与模型上下文。 */
    public String maskAll(String text) {
        if (text == null || text.isEmpty()) {
            return text;
        }
        String result = PHONE.matcher(text).replaceAll("$1****$3");
        result = EMAIL.matcher(result).replaceAll("$1***$2");
        result = ID_CARD.matcher(result).replaceAll("$1**********$2");
        return BANK_CARD.matcher(result).replaceAll("$1********$2");
    }

    public boolean containsPii(String text) {
        if (text == null || text.isEmpty()) {
            return false;
        }
        return PHONE.matcher(text).find() || EMAIL.matcher(text).find() || ID_CARD.matcher(text).find();
    }
}
