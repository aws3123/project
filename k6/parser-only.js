// AST parsing throughput test — exercises TreeSitterNativeParser via /api/internal/chunk
// Run: k6 run --vus 10 --duration 30s k6/parser-only.js

import http from 'k6/http';
import { check, sleep } from 'k6';

const javaSource = `
package com.example;
import java.util.List;
import org.springframework.stereotype.Service;
import org.springframework.beans.factory.annotation.Autowired;

@Service
public class UserService {
    private final UserRepository userRepository;
    private final CacheManager cacheManager;

    @Autowired
    public UserService(UserRepository userRepository, CacheManager cacheManager) {
        this.userRepository = userRepository;
        this.cacheManager = cacheManager;
    }

    public String getUserName(Long id) {
        if (id == null) {
            throw new IllegalArgumentException("ID must not be null");
        }
        String cached = cacheManager.get("user:" + id);
        if (cached != null) {
            return cached;
        }
        User user = userRepository.findById(id);
        if (user == null) {
            throw new ResourceNotFoundException("User not found: " + id);
        }
        cacheManager.set("user:" + id, user.getName());
        return user.getName();
    }

    public void deleteUser(Long id) {
        userRepository.deleteById(id);
        cacheManager.evict("user:" + id);
    }

    private void validateUser(User user) {
        if (user.getEmail() == null || !user.getEmail().contains("@")) {
            throw new ValidationException("Invalid email");
        }
        if (user.getName() == null || user.getName().trim().isEmpty()) {
            throw new ValidationException("Name required");
        }
    }

    public List<User> searchUsers(String query, int page, int size) {
        if (page < 0 || size <= 0 || size > 100) {
            throw new IllegalArgumentException("Invalid pagination params");
        }
        return userRepository.search(query, page, size);
    }
}
`;

const pythonSource = `
import os
import logging
from typing import Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)

@dataclass
class User:
    id: int
    name: str
    email: str

class UserService:
    def __init__(self, repository, cache):
        self.repository = repository
        self.cache = cache

    def get_user_name(self, user_id: int) -> Optional[str]:
        if user_id is None:
            raise ValueError("ID must not be null")
        cached = self.cache.get(f"user:{user_id}")
        if cached:
            return cached
        user = self.repository.find_by_id(user_id)
        if user is None:
            return None
        self.cache.set(f"user:{user_id}", user.name)
        return user.name

    def search_users(self, query: str, page: int = 0, size: int = 20) -> list[User]:
        if page < 0 or size <= 0 or size > 100:
            raise ValueError("Invalid pagination")
        return self.repository.search(query, page, size)
`;

const TARGET_URL = __ENV.TARGET_URL || 'http://localhost:8080';

export const options = {
    stages: [
        { duration: '30s', target: 10 },
        { duration: '1m', target: 50 },
        { duration: '30s', target: 0 },
    ],
    thresholds: {
        http_req_duration: ['p(95)<500'],
        http_req_failed: ['rate<0.01'],
    },
};

export default function () {
    const javaPayload = JSON.stringify({
        sourceCode: javaSource,
        language: 'JAVA',
        filePath: 'UserService.java',
        maxChars: 800,
        overlap: 100,
    });

    const javaRes = http.post(`${TARGET_URL}/api/internal/chunk`, javaPayload, {
        headers: { 'Content-Type': 'application/json', 'X-API-Key': 'dev-key' },
    });

    check(javaRes, {
        'Java parse status 200': (r) => r.status === 200,
        'Java parse returns chunks': (r) => {
            try { return JSON.parse(r.body).totalChunks >= 3; }
            catch { return false; }
        },
    });

    const pyPayload = JSON.stringify({
        sourceCode: pythonSource,
        language: 'PYTHON',
        filePath: 'user_service.py',
        maxChars: 800,
        overlap: 100,
    });

    const pyRes = http.post(`${TARGET_URL}/api/internal/chunk`, pyPayload, {
        headers: { 'Content-Type': 'application/json', 'X-API-Key': 'dev-key' },
    });

    check(pyRes, {
        'Python parse status 200': (r) => r.status === 200,
        'Python parse returns chunks': (r) => {
            try { return JSON.parse(r.body).totalChunks >= 2; }
            catch { return false; }
        },
    });

    sleep(0.1);
}
