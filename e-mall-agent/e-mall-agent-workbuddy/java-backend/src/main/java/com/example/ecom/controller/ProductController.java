package com.example.ecom.controller;

import com.example.ecom.domain.Product;
import com.example.ecom.domain.User;
import com.example.ecom.observability.TraceContext;
import com.example.ecom.repository.ProductRepository;
import com.example.ecom.security.ApiException;
import com.example.ecom.security.RbacGuard;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

import java.util.List;

@RestController
@RequestMapping("/api/products")
public class ProductController {

    private final ProductRepository repository;
    private final RbacGuard rbac;

    public ProductController(ProductRepository repository, RbacGuard rbac) {
        this.repository = repository;
        this.rbac = rbac;
    }

    /** 兼容 Python 后端的 query 参数与契约中的 q 参数。 */
    @GetMapping
    public List<Product> products(
            @RequestParam(required = false) String q,
            @RequestParam(required = false) String query,
            @RequestParam(required = false) String category) {
        rbac.require(TraceContext.user(), "product:read");
        String keyword = q != null && !q.isBlank() ? q : query;
        if (keyword != null && !keyword.isBlank()) {
            List<Product> found = repository.search(keyword.trim());
            if (category != null && !category.isBlank()) {
                return found.stream().filter(p -> p.getCategory().equalsIgnoreCase(category)).toList();
            }
            return found;
        }
        if (category != null && !category.isBlank()) return repository.findByCategory(category.trim());
        return repository.findAll();
    }

    @GetMapping("/{id}")
    public Product product(@PathVariable String id) {
        rbac.require(TraceContext.user(), "product:read");
        return repository.findById(id)
                .orElseThrow(() -> new ApiException(HttpStatus.NOT_FOUND, "商品不存在"));
    }
}
