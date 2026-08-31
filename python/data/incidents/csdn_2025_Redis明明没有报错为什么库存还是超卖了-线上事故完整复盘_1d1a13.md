---
source: csdn
title: "Redis明明没有报错为什么库存还是超卖了-线上事故完整复盘"
url: https://blog.csdn.net/iamchb/article/details/161821603
date: 2025
---

## 一、事故背景

项目是一套电商秒杀系统。

技术架构：

- Spring Boot
- Redis
- MySQL
- RabbitMQ
- Nginx

业务流程：

```
用户下单
↓
Redis扣库存
↓
发送MQ
↓
创建订单
↓
更新数据库库存
```

活动开始前配置：

```
商品：运动耳机
库存：1000
预计流量：8万
```

活动开始后十分钟。

客服收到投诉：

```
已经下单成功
却显示库存不足
```

随后运营发现：

```
订单数：1037
库存：1000
```

系统出现超卖。

---

## 二、第一轮排查

### 怀疑Redis异常

第一反应自然是 Redis。

检查：

- CPU
- 内存
- 网络
- 慢查询日志
- 主从状态

全部正常。

监控没有任何异常。

Redis 甚至没有一条错误日志。

### 检查扣库存代码

```java
Long remain = redisTemplate.opsForValue()
    .decrement("stock:1001");

if(remain < 0){
    throw new RuntimeException("库存不足");
}
```

代码没有明显问题。

Redis DECR 是原子操作。

理论上不会超卖。

---

## 三、错误方向分析

### 错误方向1：Redis不原子

很多开发者会认为：

高并发下是不是 Redis 自己出了问题？

实际上：

Redis 单线程执行命令。

DECR 本身具有原子性。

所以：

```
Redis原子 ≠ 整个业务原子
```

这是很多人的误区。

### 错误方向2：主从延迟

有人怀疑：

读到了从库旧数据。

检查后发现：

库存操作全部走主库。

没有读写分离。

排除。

---

## 四、真正的问题出现了

继续追踪链路。

发现订单系统引入了 MQ。

架构如下：

```
用户下单 → Redis扣库存 → 发送MQ → 订单服务 → 数据库
```

事故期间。

RabbitMQ 出现积压。

部分消息发送超时。

这里埋下了隐患。

---

## 五、根因分析

出现以下情况：

场景A：

```
Redis扣减成功
↓
MQ发送失败
↓
订单创建失败
```

库存减少。

订单没有。

此时系统进入不一致状态。

为了恢复。

运维执行库存补偿。

```
库存+1
```

问题看似解决。

实际上部分消息后来恢复成功。

于是：

```
库存补偿 + 订单再次创建
```

最终导致超卖。

---

## 六、为什么监控没有发现

技术监控只关注：

- Redis
- MySQL
- MQ
- CPU
- 内存

但缺少业务监控。

例如：

```
库存扣减成功数
订单创建成功数
库存回滚数
```

这些指标没人看。

于是：

技术正常。

业务异常。

---

## 七、如何复现问题

测试代码：

```java
decreaseStock();
sendMessage();
throw new RuntimeException();
```

结果：

```
Redis库存减少
订单失败
库存未恢复
```

数据开始不一致。

当补偿逻辑介入时。

风险进一步扩大。

---

## 八、解决方案对比

### 方案一：分布式锁

```java
RLock lock = redissonClient.getLock("stock");

lock.lock();
try{
    //扣库存
}finally{
    lock.unlock();
}
```

优点：简单。

缺点：吞吐量下降。

---

### 方案二：Lua脚本

```lua
local stock = redis.call('get', KEYS[1])

if tonumber(stock) <= 0 then
    return -1
end

redis.call('decr', KEYS[1])

return 1
```

优点：高性能。

缺点：无法解决链路一致性。

---

### 方案三：库存预占

流程：

```
预占库存
↓
创建订单
↓
支付成功
↓
正式扣减
```

失败则释放。

这是很多大型电商的方案。

---

## 九、幂等设计

消费端必须保证：

```java
if(orderExists(orderNo)){
    return;
}
```

否则：

消息重复投递。

订单重复创建。

库存再次异常。

---

## 十、库存流水设计

建立流水表：

```sql
CREATE TABLE stock_flow(
    id BIGINT,
    order_no VARCHAR(64),
    product_id BIGINT,
    change_num INT,
    create_time DATETIME
);
```

任何库存变化必须记录。

方便审计。

方便追溯。

方便补偿。

---

## 十一、最终架构

```
Redis预扣库存 → 发送MQ → 订单创建 → 支付成功 → 正式扣减库存
                                                    ↓ 失败
                                                  回滚释放库存
```

上线后经历多次大促。

未再出现超卖。

---

## 十二、事故复盘总结

这次事故最重要的结论：

很多开发者把：

```
Redis原子操作
```

等同于：

```
系统不会超卖
```

实际上：

Redis 只能保证命令原子。

不能保证整个业务链路一致。

真正需要关注的是：

- 幂等
- 补偿
- 流水
- MQ可靠性
- 业务监控