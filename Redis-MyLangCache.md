# 基于 Redis Vector Search 实现 MyLangCache

## 一、设计目标

使用 Redis Stack 的向量搜索能力，实现一个类似 Redis LangCache 的语义缓存。

流程：

```text
Prompt
 ↓
Embedding
 ↓
Redis Vector Search
 ↓
找到相似问题
 ↓
返回历史答案
```

---

## 二、数据结构设计

```json
{
    "question":"ETC活动怎么领取奖励",
    "answer":"用户达标后系统自动发放奖励，T+1到账",
    "vector":[0.12,0.56,0.78],
    "createTime":1750677000
}
```

Key：

```text
langcache:1
langcache:2
```
---

## 三、创建 Redis 向量索引

```shell
FT.CREATE idx_langcache
ON JSON
PREFIX 1 langcache:
SCHEMA
$.question AS question TEXT
$.answer AS answer TEXT
$.createTime AS createTime NUMERIC
$.vector AS vector VECTOR HNSW 6
TYPE FLOAT32
DIM 1024
DISTANCE_METRIC COSINE
```

---

## 四、实体定义

```java
@Data
public class CacheRecord {

    private String id;

    private String question;

    private String answer;

    private float[] vector;

    private Long createTime;

}
```

---

## 五、Embedding 服务

```java
@Service
public class EmbeddingService {

    public float[] embedding(String text){

        return embeddingModel.embed(text);

    }

}
```

---

## 六、MyLangCache 查询实现

```java
@Service
public class MyLangCache {

    @Autowired
    private EmbeddingService embeddingService;

    @Autowired
    private JedisPooled jedis;

    public String get(String question){

        float[] vector =
                embeddingService.embedding(question);

        byte[] query =
                floatArrayToByteArray(vector);

        String q = "*=>[KNN 1 @vector $BLOB AS score]";

        Query queryObj = new Query(q)
                .addParam("BLOB", query)
                .returnFields("answer","score")
                .dialect(2);

        SearchResult result =
                jedis.ftSearch("idx_langcache",queryObj);

        if(result.getDocuments().isEmpty()){
            return null;
        }

        Document doc =
                result.getDocuments().get(0);

        double score =
                Double.parseDouble(doc.getString("score"));

        if(score < 0.1){
            return doc.getString("answer");
        }

        return null;

    }

}
```

---

## 七、写入缓存

```java
public void put(String question,
                String answer){

    float[] vector =
            embeddingService.embedding(question);

    String id =
            UUID.randomUUID().toString();

    CacheRecord record =
            new CacheRecord();

    record.setQuestion(question);
    record.setAnswer(answer);
    record.setVector(vector);
    record.setCreateTime(System.currentTimeMillis());

    jedis.jsonSet(
            "langcache:"+id,
            record
    );

}
```

---

## 八、ChatService

```java
@Service
public class ChatService {

    @Autowired
    private MyLangCache myLangCache;

    @Autowired
    private RagService ragService;

    @Autowired
    private DeepSeekService deepSeekService;


    public String ask(String question){

        String answer =
                myLangCache.get(question);

        if(answer != null){

            log.info("LangCache Hit");

            return answer;
        }

        log.info("LangCache Miss");

        String knowledge =
                ragService.search(question);

        answer =
                deepSeekService.chat(
                        question,
                        knowledge);

        myLangCache.put(
                question,
                answer);

        return answer;

    }

}
```

---

## 九、执行流程

第一次请求：

```text
MyLangCache
↓
Miss
↓
RAG
↓
DeepSeek
↓
put
↓
返回
```

第二次请求：

```text
用户：怎么领取ETC奖励？
↓
Embedding
↓
Redis Vector Search
↓
distance=0.04
↓
Hit
↓
直接返回
```

---

## 十、生产级增强

### TTL

```java
expire("langcache:"+id,86400);
```

### 用户隔离

增加 tenantId 字段。

### TopK 查询

```text
KNN 5
```

### 两级缓存

```text
Caffeine
↓
Redis Vector
↓
RAG
↓
LLM
```

### 防缓存击穿

```java
synchronized(question.intern())
```

或者使用 Redisson 分布式锁。

---

## 最终架构

```text
用户
 ↓
Caffeine

 ↓ miss

MyLangCache
(Redis Vector)

 ↓ miss

ES+BM25+向量库

 ↓

DeepSeek

 ↓

回写 LangCache

 ↓

返回
```

该方案本质上是利用 Redis Stack 的向量搜索能力，自实现一个免费的 LangCache。
