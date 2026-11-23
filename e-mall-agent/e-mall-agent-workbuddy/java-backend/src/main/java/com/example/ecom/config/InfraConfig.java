package com.example.ecom.config;

import com.zaxxer.hikari.HikariConfig;
import com.zaxxer.hikari.HikariDataSource;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.context.annotation.Primary;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;

import javax.sql.DataSource;
import java.util.List;

/**
 * 基础设施配置：数据源按环境变量在 MySQL 8 与进程内 H2 之间切换。
 * 未配置 MYSQL_URL 时使用 H2，保证零依赖可启动。
 */
@Configuration
public class InfraConfig {

    @Bean
    @Primary
    public DataSource dataSource(
            @org.springframework.beans.factory.annotation.Value("${MYSQL_URL:jdbc:h2:mem:ecom;MODE=MySQL;DB_CLOSE_DELAY=-1;DATABASE_TO_LOWER=TRUE}") String url,
            @org.springframework.beans.factory.annotation.Value("${MYSQL_USER:sa}") String user,
            @org.springframework.beans.factory.annotation.Value("${MYSQL_PASSWORD:}") String password,
            @org.springframework.beans.factory.annotation.Value("${DB_POOL_SIZE:10}") int poolSize) {

        HikariConfig cfg = new HikariConfig();
        cfg.setJdbcUrl(url);
        cfg.setUsername(user);
        cfg.setPassword(password);
        cfg.setMaximumPoolSize(poolSize);
        cfg.setDriverClassName(url.startsWith("jdbc:mysql") ? "com.mysql.cj.jdbc.Driver" : "org.h2.Driver");
        cfg.setPoolName("ecom-hikari");
        return new HikariDataSource(cfg);
    }

    /** 幂等种子数据：商品与三级角色用户，H2/MySQL 通用。 */
    @Bean
    @Order(Ordered.LOWEST_PRECEDENCE - 100)
    public ApplicationRunner dataSeeder(
            com.example.ecom.repository.ProductRepository products,
            com.example.ecom.repository.UserRepository users,
            com.example.ecom.repository.OrderRepository orders) {
        return (ApplicationArguments args) -> {
            // 与 Python 后端 InMemoryRepository / MySQL 初始化脚本保持同一套种子，
            // 保证共用前端在两套引擎之间切换时看到相同的商品、订单与账号。
            if (products.count() == 0) {
                products.saveAll(List.of(
                        new com.example.ecom.domain.Product("P001", "无线降噪耳机 Pro", "数码", 899.0, 12,
                                List.of("音频", "热销", "降噪"), "40小时续航，主动降噪，适合通勤与办公。"),
                        new com.example.ecom.domain.Product("P002", "便携咖啡机", "家居", 359.0, 5,
                                List.of("咖啡", "便携"), "手压萃取，随行制作意式浓缩。"),
                        new com.example.ecom.domain.Product("P003", "人体工学椅", "家具", 1299.0, 3,
                                List.of("办公", "护腰"), "网布透气，腰托可调，久坐友好。"),
                        new com.example.ecom.domain.Product("P004", "智能手表 S2", "数码", 1099.0, 20,
                                List.of("穿戴", "健康"), "心率血氧监测，14天续航。"),
                        new com.example.ecom.domain.Product("P005", "移动电源 20000mAh", "数码", 199.0, 50,
                                List.of("充电", "出行"), "22.5W 快充，可带上飞机。"),
                        new com.example.ecom.domain.Product("P006", "机械键盘 87键", "数码", 459.0, 8,
                                List.of("键盘", "办公"), "茶轴手感，紧凑布局，支持热插拔。"),
                        new com.example.ecom.domain.Product("P007", "空气循环扇", "家电", 299.0, 0,
                                List.of("风扇", "静音"), "直流变频，低噪循环送风。"),
                        new com.example.ecom.domain.Product("P008", "保温杯 500ml", "家居", 129.0, 100,
                                List.of("水杯", "保温"), "316不锈钢，12小时保温。")
                ));
            }
            if (users.count() == 0) {
                List<com.example.ecom.domain.User> seedUsers = List.of(
                        new com.example.ecom.domain.User("U001", "张三", "customer"),
                        new com.example.ecom.domain.User("U002", "李四", "customer"),
                        new com.example.ecom.domain.User("S001", "王客服", "service"),
                        new com.example.ecom.domain.User("A001", "管理员", "admin"));
                seedUsers.forEach(u -> u.setPassword("123456"));
                users.saveAll(seedUsers);
            }
            if (orders.count() == 0) {
                com.example.ecom.domain.Order o1 = new com.example.ecom.domain.Order("O1001", "U001");
                o1.addItem(new com.example.ecom.domain.OrderItem("P001", 1, 899.0));
                o1.addItem(new com.example.ecom.domain.OrderItem("P005", 1, 199.0));
                o1.setTotal(1098.0); o1.setStatus("shipped");
                o1.setCreatedAt("2026-11-18T09:12:00+00:00");
                o1.setAddress("北京市朝阳区示例路 1 号");

                com.example.ecom.domain.Order o2 = new com.example.ecom.domain.Order("O1002", "U002");
                o2.addItem(new com.example.ecom.domain.OrderItem("P003", 1, 1299.0));
                o2.setTotal(1299.0); o2.setStatus("created");
                o2.setCreatedAt("2026-11-20T14:30:00+00:00");
                o2.setAddress("上海市浦东新区示例路 2 号");

                com.example.ecom.domain.Order o3 = new com.example.ecom.domain.Order("O1003", "U001");
                o3.addItem(new com.example.ecom.domain.OrderItem("P006", 2, 459.0));
                o3.setTotal(918.0); o3.setStatus("delivered");
                o3.setCreatedAt("2026-11-10T03:05:00+00:00");
                o3.setAddress("北京市朝阳区示例路 1 号");

                orders.saveAll(List.of(o1, o2, o3));
            }
        };
    }
}
