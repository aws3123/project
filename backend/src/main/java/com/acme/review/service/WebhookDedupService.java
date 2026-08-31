package com.acme.review.service;

import lombok.extern.slf4j.Slf4j;
import org.redisson.api.RLock;
import org.redisson.api.RedissonClient;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.stereotype.Service;

import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.locks.ReentrantLock;

@Slf4j
@Service
public class WebhookDedupService {

    @Autowired(required = false)
    private RedissonClient redisson;

    private final Map<String, ReentrantLock> localLocks = new ConcurrentHashMap<>();

    public boolean tryAcquire(String lockKey, long ttlSeconds) {
        if (redisson != null) {
            RLock lock = redisson.getLock(lockKey);
            try {
                boolean acquired = lock.tryLock(0, ttlSeconds, TimeUnit.SECONDS);
                if (acquired) {
                    log.debug("Acquired dedup lock key={}", lockKey);
                } else {
                    log.info("Dedup lock already held key={}", lockKey);
                }
                return acquired;
            } catch (InterruptedException e) {
                Thread.currentThread().interrupt();
                log.warn("Interrupted while acquiring dedup lock key={}", lockKey);
                return false;
            }
        }

        ReentrantLock lock = localLocks.computeIfAbsent(lockKey, key -> new ReentrantLock());
        boolean acquired = lock.tryLock();
        if (acquired) {
            log.debug("Acquired local dedup lock key={}", lockKey);
        } else {
            log.info("Local dedup lock already held key={}", lockKey);
        }
        return acquired;
    }

    public void release(String lockKey) {
        if (redisson != null) {
            RLock lock = redisson.getLock(lockKey);
            if (lock.isHeldByCurrentThread()) {
                lock.unlock();
                log.debug("Released dedup lock key={}", lockKey);
            }
            return;
        }

        ReentrantLock lock = localLocks.get(lockKey);
        if (lock != null && lock.isHeldByCurrentThread()) {
            lock.unlock();
            log.debug("Released local dedup lock key={}", lockKey);
            if (!lock.isLocked()) {
                localLocks.remove(lockKey, lock);
            }
        }
    }
}
