package com.smartcustomerservice.business.common.lock;

import com.smartcustomerservice.business.common.error.BusinessErrorCode;
import com.smartcustomerservice.business.common.error.BusinessException;
import lombok.RequiredArgsConstructor;
import org.springframework.data.redis.core.StringRedisTemplate;
import org.springframework.data.redis.core.script.DefaultRedisScript;
import org.springframework.stereotype.Service;

import java.time.Duration;
import java.util.List;
import java.util.UUID;
import java.util.function.Supplier;

/** 使用Redis SET NX和带所有权校验的Lua脚本实现短期分布式锁。 */
@Service
@RequiredArgsConstructor
public class RedisDistributedLockService {
    private static final String KEY_PREFIX = "cs:business:lock:";
    private static final DefaultRedisScript<Long> RELEASE_SCRIPT =
            new DefaultRedisScript<>(
                    "if redis.call('get', KEYS[1]) == ARGV[1] "
                            + "then return redis.call('del', KEYS[1]) else return 0 end",
                    Long.class);

    private final StringRedisTemplate redisTemplate;

    /** 获取锁后执行任务；释放时只允许删除自己持有的锁。 */
    public <T> T execute(String businessKey, Duration ttl, Supplier<T> action) {
        String key = KEY_PREFIX + businessKey;
        String ownerToken = UUID.randomUUID().toString();
        Boolean acquired = redisTemplate.opsForValue().setIfAbsent(key, ownerToken, ttl);
        if (!Boolean.TRUE.equals(acquired)) {
            throw new BusinessException(BusinessErrorCode.STATE_CONFLICT);
        }
        try {
            return action.get();
        } finally {
            redisTemplate.execute(RELEASE_SCRIPT, List.of(key), ownerToken);
        }
    }
}
