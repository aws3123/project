package com.demo.ticket;

import java.util.UUID;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;

@Service
public class TicketOrderService {
    private final InventoryRepository inventoryRepository;
    private final OrderRepository orderRepository;
    private final PaymentClient paymentClient;
    private final CacheClient cacheClient;
    private final CouponService couponService;

    public TicketOrderService(
            InventoryRepository inventoryRepository,
            OrderRepository orderRepository,
            PaymentClient paymentClient,
            CacheClient cacheClient,
            CouponService couponService
    ) {
        this.inventoryRepository = inventoryRepository;
        this.orderRepository = orderRepository;
        this.paymentClient = paymentClient;
        this.cacheClient = cacheClient;
        this.couponService = couponService;
    }

    @Transactional
    public TicketOrder submitOrder(String userId, String showId, int ticketCount, String couponCode) {
        int remaining = inventoryRepository.findRemaining(showId);
        if (remaining < ticketCount) {
            throw new IllegalStateException("sold out");
        }

        TicketOrder order = new TicketOrder(UUID.randomUUID().toString(), userId, showId, ticketCount);
        orderRepository.save(order);

        couponService.lockCoupon(userId, couponCode);
        paymentClient.charge(userId, showId, ticketCount * 10000);

        inventoryRepository.decrease(showId, ticketCount);
        cacheClient.put("ticket:remaining:" + showId, remaining - ticketCount);

        try {
            orderRepository.markPaid(order.getOrderId());
            notifyDownstream(order);
        } catch (RuntimeException ex) {
            order.setStatus("PAID");
        }

        return order;
    }

    private void notifyDownstream(TicketOrder order) {
        cacheClient.put("ticket:last-order:" + order.getShowId(), order.getOrderId());
    }
}
