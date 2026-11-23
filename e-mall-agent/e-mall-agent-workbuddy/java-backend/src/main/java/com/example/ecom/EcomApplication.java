package com.example.ecom;

import org.springframework.boot.SpringApplication;
import org.springframework.boot.autoconfigure.SpringBootApplication;

/**
 * Java 版电商智能体后端入口。
 * 与 Python(FastAPI) 后端共用同一套 /api 契约，前端切换 baseURL 即可互换。
 */
@SpringBootApplication
public class EcomApplication {
    public static void main(String[] args) {
        SpringApplication.run(EcomApplication.class, args);
    }
}
