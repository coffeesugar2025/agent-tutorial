package com.xingtu.agent.memory;

// ═══════ 文件级能力标注 ═══════
// [CAP-07] 记忆
// 职责：用户画像（user_profile）：结构化长期记忆——偏好品牌、预算区间、尺码、会员等级
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

import com.xingtu.agent.common.JsonUtil;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.stereotype.Component;

import java.math.BigDecimal;
import java.util.ArrayList;
import java.util.List;
import java.util.Map;

/**
 * 用户画像（user_profile）：结构化长期记忆——偏好品牌、预算区间、尺码、会员等级。
 * 供导购 Agent 在 prompt 中直接使用。
 */
@Component
public class UserProfileService {

    public record Profile(long userId, String nickname, String phone, String memberLevel,
                          List<String> preferredBrands, BigDecimal budgetMin, BigDecimal budgetMax,
                          Map<String, Object> sizes) {
    }

    private final JdbcTemplate jdbc;

    public UserProfileService(JdbcTemplate jdbc) {
        this.jdbc = jdbc;
    }

    public Profile get(long userId) {
        return com.xingtu.agent.infra.JdbcSupport.one(jdbc,
                "SELECT user_id, nickname, phone, member_level, preferred_brands, budget_min, budget_max, sizes "
                        + "FROM user_profile WHERE user_id = ?",
                (rs, rowNum) -> {
                    List<String> brands = new ArrayList<>();
                    List<Object> raw = JsonUtil.parseList(rs.getString("preferred_brands"));
                    for (Object item : raw) {
                        if (item != null) {
                            brands.add(String.valueOf(item));
                        }
                    }
                    return new Profile(
                            rs.getLong("user_id"),
                            rs.getString("nickname"),
                            rs.getString("phone"),
                            rs.getString("member_level"),
                            brands,
                            rs.getBigDecimal("budget_min"),
                            rs.getBigDecimal("budget_max"),
                            JsonUtil.parseMap(rs.getString("sizes")));
                },
                userId);
    }

    public void savePreferredBrands(long userId, List<String> brands) {
        ensureRow(userId);
        jdbc.update("UPDATE user_profile SET preferred_brands = ? WHERE user_id = ?",
                JsonUtil.toJson(brands), userId);
    }

    public void saveBudget(long userId, BigDecimal min, BigDecimal max) {
        ensureRow(userId);
        jdbc.update("UPDATE user_profile SET budget_min = ?, budget_max = ? WHERE user_id = ?", min, max, userId);
    }

    public void saveSizes(long userId, Map<String, Object> sizes) {
        ensureRow(userId);
        jdbc.update("UPDATE user_profile SET sizes = ? WHERE user_id = ?", JsonUtil.toJson(sizes), userId);
    }

    public void ensureRow(long userId) {
        Integer count = jdbc.queryForObject("SELECT COUNT(*) FROM user_profile WHERE user_id = ?",
                Integer.class, userId);
        if (count == null || count == 0) {
            jdbc.update("INSERT INTO user_profile (user_id, member_level) VALUES (?, 'NORMAL')", userId);
        }
    }

    /** 渲染成 prompt 片段。 */
    public String render(long userId) {
        Profile profile = get(userId);
        if (profile == null) {
            return "";
        }
        StringBuilder sb = new StringBuilder();
        if (!profile.preferredBrands().isEmpty()) {
            sb.append("- 偏好品牌: ").append(String.join(",", profile.preferredBrands())).append('\n');
        }
        if (profile.budgetMax() != null) {
            sb.append("- 预算上限: ").append(profile.budgetMax()).append('\n');
        }
        if (profile.memberLevel() != null) {
            sb.append("- 会员等级: ").append(profile.memberLevel()).append('\n');
        }
        if (profile.sizes() != null && !profile.sizes().isEmpty()) {
            sb.append("- 尺码: ").append(JsonUtil.toJson(profile.sizes())).append('\n');
        }
        return sb.toString();
    }
}
