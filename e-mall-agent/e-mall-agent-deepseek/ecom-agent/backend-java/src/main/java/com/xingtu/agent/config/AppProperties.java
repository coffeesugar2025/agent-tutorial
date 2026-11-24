package com.xingtu.agent.config;

// ═══════ 文件级能力标注 ═══════
// [CAP-02] 模型接入与输出控制  |  [CAP-14] 可靠性/降级  （支撑）
// 职责：全局配置（app
// 能力编号与规范见 docs/11-代码能力标注规范.md
// ══════════════════════════════════

import org.springframework.boot.context.properties.ConfigurationProperties;

import java.util.ArrayList;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;

/**
 * 全局配置（app.*），环境变量与 Python 端同名同义。
 */
@ConfigurationProperties(prefix = "app")
public class AppProperties {

    private String env = "dev";
    private Agent agent = new Agent();
    private Jwt jwt = new Jwt();
    private Llm llm = new Llm();
    private Embedding embedding = new Embedding();
    private Milvus milvus = new Milvus();
    private Rag rag = new Rag();
    private Pricing pricing = new Pricing();
    private Mq mq = new Mq();
    private Security security = new Security();
    private Sandbox sandbox = new Sandbox();
    private Eval eval = new Eval();

    public String getEnv() {
        return env;
    }

    public void setEnv(String env) {
        this.env = env;
    }

    public Agent getAgent() {
        return agent;
    }

    public void setAgent(Agent agent) {
        this.agent = agent;
    }

    public Jwt getJwt() {
        return jwt;
    }

    public void setJwt(Jwt jwt) {
        this.jwt = jwt;
    }

    public Llm getLlm() {
        return llm;
    }

    public void setLlm(Llm llm) {
        this.llm = llm;
    }

    public Embedding getEmbedding() {
        return embedding;
    }

    public void setEmbedding(Embedding embedding) {
        this.embedding = embedding;
    }

    public Milvus getMilvus() {
        return milvus;
    }

    public void setMilvus(Milvus milvus) {
        this.milvus = milvus;
    }

    public Rag getRag() {
        return rag;
    }

    public void setRag(Rag rag) {
        this.rag = rag;
    }

    public Pricing getPricing() {
        return pricing;
    }

    public void setPricing(Pricing pricing) {
        this.pricing = pricing;
    }

    public Mq getMq() {
        return mq;
    }

    public void setMq(Mq mq) {
        this.mq = mq;
    }

    public Security getSecurity() {
        return security;
    }

    public void setSecurity(Security security) {
        this.security = security;
    }

    public Sandbox getSandbox() {
        return sandbox;
    }

    public void setSandbox(Sandbox sandbox) {
        this.sandbox = sandbox;
    }

    public Eval getEval() {
        return eval;
    }

    public void setEval(Eval eval) {
        this.eval = eval;
    }

    /** Agent 运行时约束（对应 docs/00 第 5 节终止条件）。 */
    public static class Agent {
        private int maxSteps = 12;
        private int maxTokenBudget = 60000;
        private int taskTimeoutSeconds = 120;
        private long approvalAmountThresholdCents = 100000L;
        private int rateLimitPerMinute = 30;
        private int memoryWindow = 20;
        private int summaryThreshold = 40;
        private int maxToolResultChars = 4000;
        private boolean checkpointEnabled = true;

        public int getMaxSteps() {
            return maxSteps;
        }

        public void setMaxSteps(int maxSteps) {
            this.maxSteps = maxSteps;
        }

        public int getMaxTokenBudget() {
            return maxTokenBudget;
        }

        public void setMaxTokenBudget(int maxTokenBudget) {
            this.maxTokenBudget = maxTokenBudget;
        }

        public int getTaskTimeoutSeconds() {
            return taskTimeoutSeconds;
        }

        public void setTaskTimeoutSeconds(int taskTimeoutSeconds) {
            this.taskTimeoutSeconds = taskTimeoutSeconds;
        }

        public long getApprovalAmountThresholdCents() {
            return approvalAmountThresholdCents;
        }

        public void setApprovalAmountThresholdCents(long approvalAmountThresholdCents) {
            this.approvalAmountThresholdCents = approvalAmountThresholdCents;
        }

        public int getRateLimitPerMinute() {
            return rateLimitPerMinute;
        }

        public void setRateLimitPerMinute(int rateLimitPerMinute) {
            this.rateLimitPerMinute = rateLimitPerMinute;
        }

        public int getMemoryWindow() {
            return memoryWindow;
        }

        public void setMemoryWindow(int memoryWindow) {
            this.memoryWindow = memoryWindow;
        }

        public int getSummaryThreshold() {
            return summaryThreshold;
        }

        public void setSummaryThreshold(int summaryThreshold) {
            this.summaryThreshold = summaryThreshold;
        }

        public int getMaxToolResultChars() {
            return maxToolResultChars;
        }

        public void setMaxToolResultChars(int maxToolResultChars) {
            this.maxToolResultChars = maxToolResultChars;
        }

        public boolean isCheckpointEnabled() {
            return checkpointEnabled;
        }

        public void setCheckpointEnabled(boolean checkpointEnabled) {
            this.checkpointEnabled = checkpointEnabled;
        }
    }

    public static class Jwt {
        private String secret = "change-me-in-prod";
        private long expireSeconds = 86400L;

        public String getSecret() {
            return secret;
        }

        public void setSecret(String secret) {
            this.secret = secret;
        }

        public long getExpireSeconds() {
            return expireSeconds;
        }

        public void setExpireSeconds(long expireSeconds) {
            this.expireSeconds = expireSeconds;
        }
    }

    public static class Llm {
        private String primary = "deepseek";
        private boolean mock = false;
        private double temperature = 0.3d;
        private int maxTokens = 1024;
        private int timeoutSeconds = 45;
        private String rerankProvider = "llm";
        private List<String> fallbackChain = new ArrayList<>();
        private Map<String, Provider> providers = new LinkedHashMap<>();

        public String getPrimary() {
            return primary;
        }

        public void setPrimary(String primary) {
            this.primary = primary;
        }

        public boolean isMock() {
            return mock;
        }

        public void setMock(boolean mock) {
            this.mock = mock;
        }

        public double getTemperature() {
            return temperature;
        }

        public void setTemperature(double temperature) {
            this.temperature = temperature;
        }

        public int getMaxTokens() {
            return maxTokens;
        }

        public void setMaxTokens(int maxTokens) {
            this.maxTokens = maxTokens;
        }

        public int getTimeoutSeconds() {
            return timeoutSeconds;
        }

        public void setTimeoutSeconds(int timeoutSeconds) {
            this.timeoutSeconds = timeoutSeconds;
        }

        public String getRerankProvider() {
            return rerankProvider;
        }

        public void setRerankProvider(String rerankProvider) {
            this.rerankProvider = rerankProvider;
        }

        public List<String> getFallbackChain() {
            return fallbackChain;
        }

        public void setFallbackChain(List<String> fallbackChain) {
            this.fallbackChain = fallbackChain;
        }

        public Map<String, Provider> getProviders() {
            return providers;
        }

        public void setProviders(Map<String, Provider> providers) {
            this.providers = providers;
        }
    }

    /** 单个模型供应商（OpenAI 兼容协议）。 */
    public static class Provider {
        private String baseUrl = "";
        private String apiKey = "";
        private String model = "";
        private boolean logRequests = false;

        public String getBaseUrl() {
            return baseUrl;
        }

        public void setBaseUrl(String baseUrl) {
            this.baseUrl = baseUrl;
        }

        public String getApiKey() {
            return apiKey;
        }

        public void setApiKey(String apiKey) {
            this.apiKey = apiKey;
        }

        public String getModel() {
            return model;
        }

        public void setModel(String model) {
            this.model = model;
        }

        public boolean isLogRequests() {
            return logRequests;
        }

        public void setLogRequests(boolean logRequests) {
            this.logRequests = logRequests;
        }
    }

    public static class Embedding {
        private String provider = "dashscope";
        private String model = "text-embedding-v3";
        private int dim = 1024;
        private String baseUrl = "";
        private String apiKey = "";

        public String getProvider() {
            return provider;
        }

        public void setProvider(String provider) {
            this.provider = provider;
        }

        public String getModel() {
            return model;
        }

        public void setModel(String model) {
            this.model = model;
        }

        public int getDim() {
            return dim;
        }

        public void setDim(int dim) {
            this.dim = dim;
        }

        public String getBaseUrl() {
            return baseUrl;
        }

        public void setBaseUrl(String baseUrl) {
            this.baseUrl = baseUrl;
        }

        public String getApiKey() {
            return apiKey;
        }

        public void setApiKey(String apiKey) {
            this.apiKey = apiKey;
        }
    }

    public static class Milvus {
        private boolean enabled = true;
        private String host = "milvus";
        private int port = 19530;
        private int restPort = 9091;
        private String token = "root:Milvus";
        private String collectionPrefix = "ecom";
        private int timeoutMs = 3000;

        public boolean isEnabled() {
            return enabled;
        }

        public void setEnabled(boolean enabled) {
            this.enabled = enabled;
        }

        public String getHost() {
            return host;
        }

        public void setHost(String host) {
            this.host = host;
        }

        public int getPort() {
            return port;
        }

        public void setPort(int port) {
            this.port = port;
        }

        public int getRestPort() {
            return restPort;
        }

        public void setRestPort(int restPort) {
            this.restPort = restPort;
        }

        public String getToken() {
            return token;
        }

        public void setToken(String token) {
            this.token = token;
        }

        public String getCollectionPrefix() {
            return collectionPrefix;
        }

        public void setCollectionPrefix(String collectionPrefix) {
            this.collectionPrefix = collectionPrefix;
        }

        public int getTimeoutMs() {
            return timeoutMs;
        }

        public void setTimeoutMs(int timeoutMs) {
            this.timeoutMs = timeoutMs;
        }
    }

    public static class Rag {
        private int chunkSize = 520;
        private int chunkOverlap = 80;
        private int denseTopK = 20;
        private int sparseTopK = 20;
        private int rerankTopN = 5;
        private double minScore = 0.05d;
        private int candidateLimit = 3000;

        public int getChunkSize() {
            return chunkSize;
        }

        public void setChunkSize(int chunkSize) {
            this.chunkSize = chunkSize;
        }

        public int getChunkOverlap() {
            return chunkOverlap;
        }

        public void setChunkOverlap(int chunkOverlap) {
            this.chunkOverlap = chunkOverlap;
        }

        public int getDenseTopK() {
            return denseTopK;
        }

        public void setDenseTopK(int denseTopK) {
            this.denseTopK = denseTopK;
        }

        public int getSparseTopK() {
            return sparseTopK;
        }

        public void setSparseTopK(int sparseTopK) {
            this.sparseTopK = sparseTopK;
        }

        public int getRerankTopN() {
            return rerankTopN;
        }

        public void setRerankTopN(int rerankTopN) {
            this.rerankTopN = rerankTopN;
        }

        public double getMinScore() {
            return minScore;
        }

        public void setMinScore(double minScore) {
            this.minScore = minScore;
        }

        public int getCandidateLimit() {
            return candidateLimit;
        }

        public void setCandidateLimit(int candidateLimit) {
            this.candidateLimit = candidateLimit;
        }
    }

    /** 价格表：单位「分 / 百万 token」。 */
    public static class Pricing {
        private int defaultInputPerMillionCents = 200;
        private int defaultOutputPerMillionCents = 800;
        private Map<String, Price> models = new LinkedHashMap<>();

        public int getDefaultInputPerMillionCents() {
            return defaultInputPerMillionCents;
        }

        public void setDefaultInputPerMillionCents(int defaultInputPerMillionCents) {
            this.defaultInputPerMillionCents = defaultInputPerMillionCents;
        }

        public int getDefaultOutputPerMillionCents() {
            return defaultOutputPerMillionCents;
        }

        public void setDefaultOutputPerMillionCents(int defaultOutputPerMillionCents) {
            this.defaultOutputPerMillionCents = defaultOutputPerMillionCents;
        }

        public Map<String, Price> getModels() {
            return models;
        }

        public void setModels(Map<String, Price> models) {
            this.models = models;
        }
    }

    public static class Price {
        private int inputPerMillionCents;
        private int outputPerMillionCents;

        public int getInputPerMillionCents() {
            return inputPerMillionCents;
        }

        public void setInputPerMillionCents(int inputPerMillionCents) {
            this.inputPerMillionCents = inputPerMillionCents;
        }

        public int getOutputPerMillionCents() {
            return outputPerMillionCents;
        }

        public void setOutputPerMillionCents(int outputPerMillionCents) {
            this.outputPerMillionCents = outputPerMillionCents;
        }
    }

    public static class Mq {
        private boolean enabled = true;
        private String exchange = "ecom.agent";
        private String dlx = "ecom.agent.dlx";

        public boolean isEnabled() {
            return enabled;
        }

        public void setEnabled(boolean enabled) {
            this.enabled = enabled;
        }

        public String getExchange() {
            return exchange;
        }

        public void setExchange(String exchange) {
            this.exchange = exchange;
        }

        public String getDlx() {
            return dlx;
        }

        public void setDlx(String dlx) {
            this.dlx = dlx;
        }
    }

    public static class Security {
        private boolean injectionDetectEnabled = true;
        private boolean piiMaskEnabled = true;

        public boolean isInjectionDetectEnabled() {
            return injectionDetectEnabled;
        }

        public void setInjectionDetectEnabled(boolean injectionDetectEnabled) {
            this.injectionDetectEnabled = injectionDetectEnabled;
        }

        public boolean isPiiMaskEnabled() {
            return piiMaskEnabled;
        }

        public void setPiiMaskEnabled(boolean piiMaskEnabled) {
            this.piiMaskEnabled = piiMaskEnabled;
        }
    }

    public static class Sandbox {
        private boolean enabled = true;
        private int maxOutputChars = 4000;

        public boolean isEnabled() {
            return enabled;
        }

        public void setEnabled(boolean enabled) {
            this.enabled = enabled;
        }

        public int getMaxOutputChars() {
            return maxOutputChars;
        }

        public void setMaxOutputChars(int maxOutputChars) {
            this.maxOutputChars = maxOutputChars;
        }
    }

    public static class Eval {
        private boolean enabled = true;
        private int defaultRepeat = 1;

        public boolean isEnabled() {
            return enabled;
        }

        public void setEnabled(boolean enabled) {
            this.enabled = enabled;
        }

        public int getDefaultRepeat() {
            return defaultRepeat;
        }

        public void setDefaultRepeat(int defaultRepeat) {
            this.defaultRepeat = defaultRepeat;
        }
    }
}
