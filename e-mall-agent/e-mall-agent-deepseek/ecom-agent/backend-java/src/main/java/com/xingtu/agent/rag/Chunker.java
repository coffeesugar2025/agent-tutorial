package com.xingtu.agent.rag;

import com.xingtu.agent.common.TokenEstimator;
import com.xingtu.agent.config.AppProperties;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Component;

import java.util.ArrayList;
import java.util.List;

/**
 * 切片器：按句子边界累积到 chunkSize，相邻块保留 overlap 个字符的重叠。
 * 同时保留 parentContent（父块），实现「命中子块、返回父块」。
 */
@Component
public class Chunker {

    public record Chunk(int index, String content, String parentContent, int tokens) {
    }

    private static final int MIN_CHUNK_SIZE = 80;

    private final int chunkSize;
    private final int overlap;

    @Autowired
    public Chunker(AppProperties props) {
        this(props.getRag().getChunkSize(), props.getRag().getChunkOverlap());
    }

    /** 测试友好构造器。 */
    public Chunker(int chunkSize, int overlap) {
        this.chunkSize = Math.max(MIN_CHUNK_SIZE, chunkSize);
        this.overlap = Math.max(0, Math.min(overlap, this.chunkSize / 2));
    }

    public List<Chunk> split(String text) {
        List<Chunk> chunks = new ArrayList<>();
        if (text == null || text.isBlank()) {
            return chunks;
        }
        String normalized = normalize(text);
        String parent = normalized.length() <= 4000 ? normalized : normalized.substring(0, 4000);
        List<String> sentences = sentences(normalized);

        StringBuilder current = new StringBuilder();
        int index = 0;
        for (String sentence : sentences) {
            if (current.length() > 0 && current.length() + sentence.length() > chunkSize) {
                chunks.add(build(index++, current.toString(), parent));
                current = overlapTail(current.toString());
            }
            if (sentence.length() > chunkSize) {
                // 超长句子（例如无标点的表格/日志）硬切
                for (int start = 0; start < sentence.length(); start += chunkSize) {
                    int end = Math.min(sentence.length(), start + chunkSize);
                    chunks.add(build(index++, sentence.substring(start, end), parent));
                }
                current.setLength(0);
                continue;
            }
            current.append(sentence);
        }
        if (current.length() > 0) {
            chunks.add(build(index, current.toString(), parent));
        }
        if (chunks.isEmpty()) {
            chunks.add(build(0, normalized, parent));
        }
        return chunks;
    }

    private Chunk build(int index, String content, String parent) {
        String trimmed = content.trim();
        return new Chunk(index, trimmed, parent, TokenEstimator.estimate(trimmed));
    }

    private StringBuilder overlapTail(String content) {
        StringBuilder tail = new StringBuilder();
        if (overlap <= 0 || content.isEmpty()) {
            return tail;
        }
        int start = Math.max(0, content.length() - overlap);
        tail.append(content, start, content.length());
        return tail;
    }

    private List<String> sentences(String text) {
        List<String> result = new ArrayList<>();
        StringBuilder current = new StringBuilder();
        for (int i = 0; i < text.length(); i++) {
            char c = text.charAt(i);
            current.append(c);
            if (isBoundary(c)) {
                result.add(current.toString());
                current.setLength(0);
            }
        }
        if (current.length() > 0) {
            result.add(current.toString());
        }
        return result;
    }

    private boolean isBoundary(char c) {
        return c == '。' || c == '！' || c == '？' || c == '；' || c == '\n' || c == '!' || c == '?' || c == ';';
    }

    private String normalize(String text) {
        String normalized = text.replace("\r\n", "\n").replace('\r', '\n');
        normalized = normalized.replaceAll("[ \t]+", " ");
        normalized = normalized.replaceAll("\n{3,}", "\n\n");
        return normalized.trim();
    }
}
